"""Alert intelligence layer: severity routing, batching, grouping, and human-friendly formatting."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from argus_agent.events.types import Event, EventSeverity, EventType

logger = logging.getLogger("argus.alerting.formatter")

# ---------------------------------------------------------------------------
# Human-friendly message templates
# ---------------------------------------------------------------------------

_SEVERITY_EMOJI = {
    EventSeverity.URGENT: "\U0001f534",   # red circle
    EventSeverity.NOTABLE: "\U0001f7e1",  # yellow circle
    EventSeverity.NORMAL: "\U0001f7e2",   # green circle
}


def _fmt_suspicious_outbound(event: Event) -> str:
    msg = event.message or ""
    ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", msg)
    port_match = re.search(r":(\d+)", msg)
    ip = ip_match.group(1) if ip_match else "unknown"
    port = port_match.group(1) if port_match else "unknown"
    return f"New connection to IP {ip} on port {port}"


def _fmt_anomaly(event: Event) -> str:
    data = event.data or {}
    metric = data.get("metric", "unknown")
    value = data.get("value", "?")
    mean = data.get("mean", data.get("baseline_mean", "?"))
    return f"{metric.replace('_', ' ').title()} spiked to {value} — normally around {mean}"


def _fmt_suspicious_process(event: Event) -> str:
    msg = event.message or ""
    proc_match = re.search(r":\s*(\S+)", msg)
    pid_match = re.search(r"PID\s*(\d+)", msg)
    proc = proc_match.group(1) if proc_match else "unknown"
    pid = pid_match.group(1) if pid_match else "?"
    return f"Suspicious process '{proc}' detected (PID {pid}) — matches known cryptominer pattern"


def _fmt_brute_force(event: Event) -> str:
    msg = event.message or ""
    count_match = re.search(r"(\d+)\s*fail", msg)
    ip_match = re.search(r"from\s+(\S+)", msg)
    count = count_match.group(1) if count_match else "many"
    ip = ip_match.group(1) if ip_match else "unknown"
    return f"SSH brute force attack: {count} failed login attempts from {ip}"


def _fmt_cpu_high(event: Event) -> str:
    data = event.data or {}
    pct = data.get("value", data.get("percent", "?"))
    if isinstance(pct, float):
        pct = round(pct)
    sev = event.severity
    word = "critically high" if sev == EventSeverity.URGENT else "elevated"
    return f"CPU usage {word} at {pct}%"


def _fmt_memory_high(event: Event) -> str:
    data = event.data or {}
    pct = data.get("value", data.get("percent", "?"))
    if isinstance(pct, float):
        pct = round(pct)
    sev = event.severity
    word = "critically high" if sev == EventSeverity.URGENT else "elevated"
    return f"Memory usage {word} at {pct}%"


def _fmt_disk_high(event: Event) -> str:
    data = event.data or {}
    pct = data.get("value", data.get("percent", "?"))
    if isinstance(pct, float):
        pct = round(pct)
    sev = event.severity
    word = "critically high" if sev == EventSeverity.URGENT else "elevated"
    return f"Disk usage {word} at {pct}%"


def _fmt_process_crashed(_event: Event) -> str:
    return "A monitored process has crashed"


def _fmt_process_oom(_event: Event) -> str:
    return "A process was killed by the OOM killer — out of memory"


def _fmt_error_burst(_event: Event) -> str:
    return "Burst of errors detected in application logs"


def _fmt_new_executable(event: Event) -> str:
    msg = event.message or ""
    path_match = re.search(r":\s*(.+)", msg)
    path = path_match.group(1).strip() if path_match else "unknown path"
    return f"New executable file appeared in temp directory: {path}"


def _fmt_new_open_port(event: Event) -> str:
    msg = event.message or ""
    port_match = re.search(r"(\d+)", msg)
    port = port_match.group(1) if port_match else "unknown"
    return f"New listening port detected: port {port} is now open"


def _fmt_permission_risk(event: Event) -> str:
    msg = event.message or ""
    file_match = re.search(r":\s*(\S+)", msg)
    mode_match = re.search(r"mode\s+(\d+)", msg)
    filepath = file_match.group(1) if file_match else "unknown"
    mode = mode_match.group(1) if mode_match else "?"
    return f"Sensitive file '{filepath}' is world-readable (permissions: {mode}) — security risk"


def _fmt_sdk_error_spike(event: Event) -> str:
    data = event.data or {}
    svc = data.get("service", "unknown")
    rate = data.get("error_rate", "?")
    prev = data.get("previous_error_rate", "?")
    return f"Error rate in '{svc}' spiked to {rate}% (was {prev}%)"


def _fmt_sdk_latency(event: Event) -> str:
    data = event.data or {}
    svc = data.get("service", "unknown")
    p95 = data.get("p95_ms", "?")
    prev = data.get("previous_p95_ms", "?")
    return f"Response time for '{svc}' degraded: p95 now {p95}ms (was {prev}ms)"


def _fmt_sdk_cold_start(event: Event) -> str:
    data = event.data or {}
    svc = data.get("service", "unknown")
    rate = data.get("cold_start_pct", "?")
    return f"Cold start rate for '{svc}' spiked to {rate}%"


def _fmt_sdk_service_silent(event: Event) -> str:
    data = event.data or {}
    svc = data.get("service", "unknown")
    return f"Service '{svc}' stopped sending telemetry — may be down"


def _fmt_sdk_traffic_burst(event: Event) -> str:
    data = event.data or {}
    svc = data.get("service", "unknown")
    count = data.get("request_count", "?")
    baseline = data.get("baseline_mean", "?")
    if isinstance(baseline, float):
        baseline = round(baseline)
    return f"Traffic spike on '{svc}': {count} requests in 5 min (normally ~{baseline})"


def _fmt_process_restart_loop(event: Event) -> str:
    data = event.data or {}
    name = data.get("process_name", "unknown")
    count = data.get("restart_count", "multiple")
    return f"Process '{name}' is stuck in a restart loop ({count} restarts)"


TEMPLATES: dict[str, Any] = {
    EventType.SUSPICIOUS_OUTBOUND: _fmt_suspicious_outbound,
    EventType.ANOMALY_DETECTED: _fmt_anomaly,
    EventType.SUSPICIOUS_PROCESS: _fmt_suspicious_process,
    EventType.BRUTE_FORCE: _fmt_brute_force,
    EventType.CPU_HIGH: _fmt_cpu_high,
    EventType.MEMORY_HIGH: _fmt_memory_high,
    EventType.DISK_HIGH: _fmt_disk_high,
    EventType.PROCESS_CRASHED: _fmt_process_crashed,
    EventType.PROCESS_OOM_KILLED: _fmt_process_oom,
    EventType.ERROR_BURST: _fmt_error_burst,
    EventType.NEW_EXECUTABLE: _fmt_new_executable,
    EventType.NEW_OPEN_PORT: _fmt_new_open_port,
    EventType.PERMISSION_RISK: _fmt_permission_risk,
    EventType.SDK_ERROR_SPIKE: _fmt_sdk_error_spike,
    EventType.SDK_LATENCY_DEGRADATION: _fmt_sdk_latency,
    EventType.SDK_COLD_START_SPIKE: _fmt_sdk_cold_start,
    EventType.SDK_SERVICE_SILENT: _fmt_sdk_service_silent,
    EventType.SDK_TRAFFIC_BURST: _fmt_sdk_traffic_burst,
    EventType.PROCESS_RESTART_LOOP: _fmt_process_restart_loop,
}


def format_event(event: Event) -> str:
    """Return a human-friendly message for an event."""
    fn = TEMPLATES.get(event.type)
    if fn is not None:
        try:
            return fn(event)
        except Exception:
            logger.debug("Template error for %s, falling back to raw message", event.type)
    return event.message or str(event.type)


# ---------------------------------------------------------------------------
# Grouping logic
# ---------------------------------------------------------------------------

def _grouping_key(alert: Any, event: Event) -> str:
    """Compute a grouping key for digest batching."""
    etype = event.type

    if etype == EventType.SUSPICIOUS_OUTBOUND:
        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", event.message or "")
        ip = ip_match.group(1) if ip_match else "unknown"
        return f"suspicious_outbound:{ip}"

    if etype == EventType.ANOMALY_DETECTED:
        metric = (event.data or {}).get("metric", "unknown")
        return f"anomaly:{metric}"

    if etype in (
        EventType.SDK_ERROR_SPIKE,
        EventType.SDK_LATENCY_DEGRADATION,
        EventType.SDK_COLD_START_SPIKE,
        EventType.SDK_SERVICE_SILENT,
        EventType.SDK_TRAFFIC_BURST,
    ):
        svc = (event.data or {}).get("service", "unknown")
        return f"{etype}:{svc}"

    return f"{alert.rule_id}:{etype}"


# ---------------------------------------------------------------------------
# Data classes for digest
# ---------------------------------------------------------------------------

@dataclass
class DigestItem:
    """A single alert+event in the buffer."""

    alert: Any
    event: Event
    friendly_message: str


@dataclass
class DigestGroup:
    """A set of related items collapsed into one line."""

    key: str
    items: list[DigestItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def summary(self) -> str:
        """Human-friendly summary for the group."""
        if self.count == 0:
            return ""

        first = self.items[0]
        etype = first.event.type

        if self.count > 1 and etype == EventType.SUSPICIOUS_OUTBOUND:
            ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", first.event.message or "")
            ip = ip_match.group(1) if ip_match else "unknown"
            return f"{self.count} new outbound connections to {ip}"

        if self.count > 1 and etype == EventType.ANOMALY_DETECTED:
            metric = (first.event.data or {}).get("metric", "unknown")
            return f"Multiple anomalies on {metric}"

        if self.count > 1:
            return f"{first.friendly_message} (+{self.count - 1} more)"

        return first.friendly_message


@dataclass
class AlertDigest:
    """A batch of grouped alerts ready for delivery."""

    groups: list[DigestGroup]
    total_count: int
    window_seconds: int
    ai_summary: str = ""


# ---------------------------------------------------------------------------
# AlertFormatter — the core intelligence layer
# ---------------------------------------------------------------------------

class AlertFormatter:
    """Routes alerts by severity, batches NOTABLE alerts, rewrites jargon."""

    def __init__(
        self,
        channels: list[Any] | None = None,
        batch_window: int = 90,
        min_severity: str = "NOTABLE",
        ai_enhance: bool = False,
    ) -> None:
        self._channels: list[Any] = channels or []
        self._batch_window = batch_window
        self._min_severity = EventSeverity(min_severity)
        self._ai_enhance = ai_enhance
        self._buffer: list[DigestItem] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False

    def set_channels(self, channels: list[Any]) -> None:
        self._channels = channels

    async def start(self) -> None:
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info(
            "AlertFormatter started (batch_window=%ds, min_severity=%s, ai_enhance=%s)",
            self._batch_window, self._min_severity, self._ai_enhance,
        )

    async def stop(self) -> None:
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final flush
        await self._flush()
        logger.info("AlertFormatter stopped")

    async def submit(self, alert: Any, event: Event) -> None:
        """Route an alert by severity: URGENT → immediate, NOTABLE → buffer."""
        severity_order = [EventSeverity.NORMAL, EventSeverity.NOTABLE, EventSeverity.URGENT]
        if severity_order.index(event.severity) < severity_order.index(self._min_severity):
            return

        friendly = format_event(event)

        if event.severity == EventSeverity.URGENT:
            await self._send_immediate(alert, event, friendly)
        else:
            item = DigestItem(alert=alert, event=event, friendly_message=friendly)
            async with self._buffer_lock:
                self._buffer.append(item)

    async def _send_immediate(self, alert: Any, event: Event, friendly: str) -> None:
        """Send an URGENT alert immediately to all external channels."""
        for channel in self._channels:
            try:
                if hasattr(channel, "send_urgent"):
                    await channel.send_urgent(alert, event, friendly)
                else:
                    await channel.send(alert, event)
            except Exception:
                logger.exception("Urgent send failed on channel %s", type(channel).__name__)

    async def send_investigation_report(self, event: Event, summary: str) -> None:
        """Post an AI investigation report to all external channels."""
        title = format_event(event)
        for channel in self._channels:
            try:
                if hasattr(channel, "send_investigation_report"):
                    await channel.send_investigation_report(title, summary)
                else:
                    logger.debug(
                        "Channel %s has no send_investigation_report",
                        type(channel).__name__,
                    )
            except Exception:
                logger.exception("Investigation report send failed on %s", type(channel).__name__)

    async def _flush_loop(self) -> None:
        """Periodically flush the buffer."""
        while self._running:
            try:
                await asyncio.sleep(self._batch_window)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Flush loop error")

    async def _flush(self) -> None:
        """Drain the buffer, group items, and deliver a digest."""
        async with self._buffer_lock:
            items = list(self._buffer)
            self._buffer.clear()

        if not items:
            return

        groups = self._group_items(items)

        ai_summary = ""
        if self._ai_enhance:
            ai_summary = await self._ai_triage(groups, items)

        digest = AlertDigest(
            groups=groups,
            total_count=len(items),
            window_seconds=self._batch_window,
            ai_summary=ai_summary,
        )

        for channel in self._channels:
            try:
                if hasattr(channel, "send_digest"):
                    await channel.send_digest(digest)
                else:
                    for item in items:
                        await channel.send(item.alert, item.event)
            except Exception:
                logger.exception("Digest send failed on %s", type(channel).__name__)

    @staticmethod
    def _group_items(items: list[DigestItem]) -> list[DigestGroup]:
        """Group items by their grouping key."""
        groups_map: dict[str, DigestGroup] = {}
        for item in items:
            key = _grouping_key(item.alert, item.event)
            if key not in groups_map:
                groups_map[key] = DigestGroup(key=key)
            groups_map[key].items.append(item)
        return list(groups_map.values())

    async def _ai_triage(self, groups: list[DigestGroup], items: list[DigestItem]) -> str:
        """Optional LLM call to summarise a NOTABLE digest batch."""
        try:
            from argus_agent.llm.registry import get_provider
            from argus_agent.scheduler.budget import get_token_budget

            budget = get_token_budget()
            if budget is not None and not budget.can_spend(1000, priority="normal"):
                return ""

            provider = get_provider()
            if provider is None:
                return ""

            summaries = [g.summary for g in groups]
            prompt = (
                "You are Argus, a server monitoring AI. Briefly assess these NOTABLE "
                "(non-critical) events in 1-2 sentences. Focus on whether action is needed.\n\n"
                + "\n".join(f"- {s}" for s in summaries)
            )
            result = await provider.chat([{"role": "user", "content": prompt}])
            return result.content if result else ""
        except Exception:
            logger.debug("AI triage skipped — no provider or budget")
            return ""
