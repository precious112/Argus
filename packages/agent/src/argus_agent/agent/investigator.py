"""Autonomous AI investigation pipeline."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from argus_agent.agent.loop import AgentLoop
from argus_agent.agent.memory import ConversationMemory
from argus_agent.api.protocol import ServerMessage, ServerMessageType
from argus_agent.events.types import Event, EventType
from argus_agent.scheduler.budget import TokenBudget

logger = logging.getLogger("argus.agent.investigator")

MAX_CONCURRENT = 2


class Investigator:
    """Orchestrates autonomous AI investigations triggered by events.

    - Budget-gated: checks ``TokenBudget`` before starting
    - Concurrency-limited to ``MAX_CONCURRENT`` simultaneous investigations
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
        self._active: int = 0
        self._lock = asyncio.Lock()

    async def investigate_event(self, event: Event) -> None:
        """Run an AI investigation for an urgent event."""
        async with self._lock:
            if self._active >= MAX_CONCURRENT:
                logger.warning("Max concurrent investigations reached, skipping")
                return
            self._active += 1

        try:
            await self._run_investigation(event)
        finally:
            async with self._lock:
                self._active -= 1

    async def _run_investigation(self, event: Event) -> None:
        investigation_id = str(uuid.uuid4())

        # Budget check — investigations are "urgent" priority
        estimated_tokens = 4000
        if not self._budget.can_spend(estimated_tokens, priority="urgent"):
            logger.warning("Budget exceeded, skipping investigation for %s", event.type)
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
                await self._formatter.send_investigation_report(event, result.content)
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
        loop = AgentLoop(provider=provider, memory=memory, budget=self._budget)

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
        loop = AgentLoop(provider=provider, memory=memory, budget=self._budget)

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
