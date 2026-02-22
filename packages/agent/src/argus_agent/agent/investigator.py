"""Autonomous AI investigation pipeline."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from argus_agent.agent.loop import AgentLoop
from argus_agent.agent.memory import ConversationMemory
from argus_agent.api.protocol import ServerMessage, ServerMessageType
from argus_agent.events.types import Event, EventType
from argus_agent.scheduler.budget import TokenBudget

logger = logging.getLogger("argus.agent.investigator")

MAX_CONCURRENT = 2
QUEUE_MAX_SIZE = 20


class InvestigationStatus(StrEnum):
    """Result of attempting to enqueue an investigation."""

    QUEUED = "queued"
    DROPPED_QUEUE_FULL = "dropped_queue_full"
    DROPPED_BUDGET = "dropped_budget"


@dataclass
class InvestigationRequest:
    """Carries all context needed to run an investigation."""

    event: Event
    alert_id: str = ""
    channel_metadata: dict[str, str] = field(default_factory=dict)


class Investigator:
    """Orchestrates autonomous AI investigations triggered by events.

    - Budget-gated: checks ``TokenBudget`` before starting
    - Queue-based dispatch with ``MAX_CONCURRENT`` worker tasks
    - Bounded queue (``QUEUE_MAX_SIZE``) to prevent unbounded memory
    - Broadcasts progress via WebSocket
    """

    def __init__(
        self,
        budget: TokenBudget,
        provider: Any = None,
        ws_manager: Any = None,
        formatter: Any = None,
    ) -> None:
        self._budget = budget
        self._provider = provider
        self._ws_manager = ws_manager
        self._formatter = formatter
        self._queue: asyncio.Queue[InvestigationRequest] = asyncio.Queue(
            maxsize=QUEUE_MAX_SIZE,
        )
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Start the worker pool."""
        for i in range(MAX_CONCURRENT):
            task = asyncio.create_task(self._worker(i))
            self._workers.append(task)
        logger.info(
            "Investigator started (%d workers, queue_max=%d)",
            MAX_CONCURRENT,
            QUEUE_MAX_SIZE,
        )

    async def stop(self) -> None:
        """Gracefully stop workers by draining the queue."""
        for _ in self._workers:
            # Sentinel: workers exit when they get None (but our queue is typed,
            # so we cancel instead)
            pass
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Investigator stopped")

    def enqueue_investigation(self, request: InvestigationRequest) -> InvestigationStatus:
        """Non-blocking enqueue with pre-flight budget check.

        Returns the status of the enqueue attempt.
        """
        estimated_tokens = 4000
        if not self._budget.can_spend(estimated_tokens, priority="urgent"):
            logger.warning(
                "Budget exceeded, dropping investigation for %s", request.event.type,
            )
            return InvestigationStatus.DROPPED_BUDGET

        try:
            self._queue.put_nowait(request)
        except asyncio.QueueFull:
            logger.warning(
                "Investigation queue full (%d), dropping request for %s",
                QUEUE_MAX_SIZE,
                request.event.type,
            )
            return InvestigationStatus.DROPPED_QUEUE_FULL

        logger.info(
            "Investigation enqueued for %s (queue depth: %d)",
            request.event.type,
            self._queue.qsize(),
        )
        return InvestigationStatus.QUEUED

    async def investigate_event(self, event: Event) -> None:
        """Backward-compat wrapper: enqueue an event for investigation."""
        request = InvestigationRequest(event=event)
        self.enqueue_investigation(request)

    async def _worker(self, worker_id: int) -> None:
        """Process investigation requests from the queue."""
        logger.debug("Investigation worker %d started", worker_id)
        try:
            while True:
                request = await self._queue.get()
                try:
                    await self._run_investigation(request)
                except Exception:
                    logger.exception(
                        "Worker %d: investigation failed for %s",
                        worker_id,
                        request.event.type,
                    )
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            logger.debug("Investigation worker %d stopped", worker_id)

    async def _run_investigation(self, request: InvestigationRequest) -> None:
        event = request.event
        investigation_id = str(uuid.uuid4())

        # Authoritative budget check at dequeue time
        estimated_tokens = 4000
        if not self._budget.can_spend(estimated_tokens, priority="urgent"):
            logger.warning("Budget exceeded at dequeue, skipping investigation for %s", event.type)
            return

        provider = self._get_provider()
        if provider is None:
            logger.warning("No LLM provider available for investigation")
            return

        # Broadcast investigation start
        await self._broadcast(ServerMessageType.INVESTIGATION_START, {
            "investigation_id": investigation_id,
            "trigger": event.message or str(event.type),
            "severity": str(event.severity),
        })

        # Build focused prompt
        prompt = self._build_prompt(event)
        memory = ConversationMemory(source="investigation")

        # Run agent loop
        async def on_event(event_type: str, data: dict[str, Any]) -> None:
            if event_type == "assistant_message_delta":
                await self._broadcast(ServerMessageType.INVESTIGATION_UPDATE, {
                    "investigation_id": investigation_id,
                    "content": data.get("content", ""),
                })

        loop = AgentLoop(
            provider=provider,
            memory=memory,
            on_event=on_event,
            budget=self._budget,
            source="investigation",
        )

        try:
            result = await loop.run(prompt)
        except Exception:
            logger.exception("Investigation failed for %s", event.type)
            result = None

        # Broadcast completion
        summary = result.content if result else "Investigation failed"
        await self._broadcast(ServerMessageType.INVESTIGATION_END, {
            "investigation_id": investigation_id,
            "summary": summary,
            "tokens_used": (result.prompt_tokens + result.completion_tokens) if result else 0,
        })

        # Post AI report to external channels (Slack, Email, Webhook)
        if self._formatter is not None and result and result.content:
            try:
                await self._formatter.send_investigation_report(
                    event, result.content, channel_metadata=request.channel_metadata,
                )
            except Exception:
                logger.exception("Failed to send investigation report to external channels")

        logger.info("Investigation %s completed for %s", investigation_id, event.type)

    async def periodic_review(self) -> None:
        """Tier 3: periodic review of recent events/metrics/alerts (every 6h)."""
        if not self._budget.can_spend(3000, priority="normal"):
            logger.info("Budget insufficient for periodic review, skipping")
            return

        provider = self._get_provider()
        if provider is None:
            return

        prompt = (
            "Review the recent system events, metrics, and alerts. "
            "Provide a brief summary of system health and any concerns. "
            "Use the available tools to check current metrics and recent events."
        )
        memory = ConversationMemory(source="periodic_review")
        loop = AgentLoop(provider=provider, memory=memory, budget=self._budget, source="periodic")

        try:
            result = await loop.run(prompt)
            if result.content:
                await self._broadcast(ServerMessageType.INVESTIGATION_END, {
                    "investigation_id": str(uuid.uuid4()),
                    "summary": result.content,
                    "type": "periodic_review",
                })
        except Exception:
            logger.exception("Periodic review failed")

    async def daily_digest(self) -> None:
        """Tier 3: comprehensive daily report (every 24h)."""
        if not self._budget.can_spend(5000, priority="normal"):
            logger.info("Budget insufficient for daily digest, skipping")
            return

        provider = self._get_provider()
        if provider is None:
            return

        prompt = (
            "Generate a comprehensive daily system report. Include: "
            "1) Overall system health assessment "
            "2) Key metrics trends (CPU, memory, disk) "
            "3) Notable events and alerts from the past 24 hours "
            "4) Security observations "
            "5) Recommendations for improvement "
            "Use the available tools to gather current data."
        )
        memory = ConversationMemory(source="daily_digest")
        loop = AgentLoop(provider=provider, memory=memory, budget=self._budget, source="periodic")

        try:
            result = await loop.run(prompt)
            if result.content:
                await self._broadcast(ServerMessageType.INVESTIGATION_END, {
                    "investigation_id": str(uuid.uuid4()),
                    "summary": result.content,
                    "type": "daily_digest",
                })
        except Exception:
            logger.exception("Daily digest failed")

    def _get_provider(self) -> Any | None:
        if self._provider is not None:
            return self._provider
        try:
            from argus_agent.llm.registry import get_provider
            return get_provider()
        except Exception:
            return None

    async def _broadcast(self, msg_type: ServerMessageType, data: dict[str, Any]) -> None:
        if self._ws_manager is None:
            return
        try:
            await self._ws_manager.broadcast(ServerMessage(type=msg_type, data=data))
        except Exception:
            logger.debug("Broadcast failed for %s", msg_type)

    @staticmethod
    def _build_prompt(event: Event) -> str:
        lines = [
            "URGENT INVESTIGATION REQUIRED",
            "",
            f"Event Type: {event.type}",
            f"Severity: {event.severity}",
            f"Source: {event.source}",
            f"Message: {event.message}",
            "",
            "Investigate this issue using the available tools. Check relevant metrics, "
            "logs, processes, and network connections. Provide a clear summary of:",
            "1. What is happening",
            "2. Likely root cause",
            "3. Recommended actions",
        ]
        if event.data:
            lines.insert(5, f"Data: {event.data}")

        if event.type == EventType.SDK_TRAFFIC_BURST:
            lines.extend([
                "",
                "TRAFFIC BURST INVESTIGATION GUIDANCE:",
                "Determine whether this is a DDoS attack or an organic traffic surge.",
                "DDoS indicators: single-IP concentration, repeated identical requests, "
                "unusual user agents, high error rates under load.",
                "Organic surge indicators: gradual ramp-up, diverse source IPs, "
                "normal error rates, recognizable referrer patterns.",
                "Check request logs for IP distribution, path patterns, and error rates.",
            ])

        return "\n".join(lines)
