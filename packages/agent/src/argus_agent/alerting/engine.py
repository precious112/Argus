"""Smart alert engine with rule evaluation."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from argus_agent.events.bus import EventBus
from argus_agent.events.types import Event, EventSeverity, EventType

logger = logging.getLogger("argus.alerting.engine")

InvestigateCallback = Callable[[Event], Coroutine[Any, Any, None]]


@dataclass
class AlertRule:
    """A rule that determines when an alert should fire."""

    id: str
    name: str
    event_types: list[str]
    min_severity: EventSeverity = EventSeverity.NOTABLE
    cooldown_seconds: int = 300  # 5 min default
    auto_investigate: bool = False


@dataclass
class ActiveAlert:
    """An alert that has been triggered."""

    id: str
    rule_id: str
    rule_name: str
    event: Event
    severity: EventSeverity
    timestamp: datetime
    resolved: bool = False
    resolved_at: datetime | None = None


# Default rules
DEFAULT_RULES: list[AlertRule] = [
    AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
    ),
    AlertRule(
        id="memory_critical",
        name="Memory Critical",
        event_types=[EventType.MEMORY_HIGH],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
    ),
    AlertRule(
        id="disk_critical",
        name="Disk Critical",
        event_types=[EventType.DISK_HIGH],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
    ),
    AlertRule(
        id="process_crash",
        name="Process Crash",
        event_types=[EventType.PROCESS_CRASHED, EventType.PROCESS_OOM_KILLED],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
    ),
    AlertRule(
        id="error_burst",
        name="Error Burst",
        event_types=[EventType.ERROR_BURST],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
    ),
    AlertRule(
        id="security_event",
        name="Security Event",
        event_types=[
            EventType.BRUTE_FORCE,
            EventType.SUSPICIOUS_PROCESS,
            EventType.NEW_EXECUTABLE,
            EventType.SUSPICIOUS_OUTBOUND,
        ],
        min_severity=EventSeverity.NOTABLE,
        auto_investigate=True,
    ),
    AlertRule(
        id="anomaly",
        name="Anomaly Detected",
        event_types=[EventType.ANOMALY_DETECTED],
        min_severity=EventSeverity.NOTABLE,
        cooldown_seconds=600,
    ),
    AlertRule(
        id="sdk_error_spike",
        name="SDK Error Rate Spike",
        event_types=[EventType.SDK_ERROR_SPIKE],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
    ),
    AlertRule(
        id="sdk_latency",
        name="SDK Latency Degradation",
        event_types=[EventType.SDK_LATENCY_DEGRADATION],
        min_severity=EventSeverity.NOTABLE,
        cooldown_seconds=600,
    ),
    AlertRule(
        id="sdk_cold_start",
        name="SDK Cold Start Spike",
        event_types=[EventType.SDK_COLD_START_SPIKE],
        min_severity=EventSeverity.NOTABLE,
        cooldown_seconds=600,
    ),
    AlertRule(
        id="sdk_service_silent",
        name="SDK Service Silent",
        event_types=[EventType.SDK_SERVICE_SILENT],
        min_severity=EventSeverity.NOTABLE,
        cooldown_seconds=1800,
    ),
]


class AlertEngine:
    """Subscribes to the event bus and fires alerts based on rules.

    Features:
    - Rule-based matching on event type + severity
    - Deduplication with configurable cooldown per rule
    - Routes alerts to notification channels
    - Optional auto-investigation callback for urgent events
    """

    def __init__(
        self,
        bus: EventBus | None = None,
        rules: list[AlertRule] | None = None,
        on_investigate: InvestigateCallback | None = None,
    ) -> None:
        self._bus = bus
        self._rules = {r.id: r for r in (rules or DEFAULT_RULES)}
        self._on_investigate = on_investigate
        self._channels: list[Any] = []  # NotificationChannel instances
        self._active_alerts: list[ActiveAlert] = []
        self._last_fired: dict[str, datetime] = {}  # rule_id -> last fire time

    def set_channels(self, channels: list[Any]) -> None:
        self._channels = channels

    async def start(self, bus: EventBus | None = None) -> None:
        """Subscribe to NOTABLE+ events on the event bus."""
        if bus is not None:
            self._bus = bus
        if self._bus is None:
            raise RuntimeError("No EventBus provided")

        self._bus.subscribe(
            self._handle_event,
            severities={EventSeverity.NOTABLE, EventSeverity.URGENT},
        )
        logger.info("Alert engine started with %d rules", len(self._rules))

    async def _handle_event(self, event: Event) -> None:
        """Evaluate all rules against an incoming event."""
        for rule in self._rules.values():
            if not self._matches(rule, event):
                continue

            # Dedup / cooldown
            now = datetime.now(UTC)
            dedup_key = f"{event.source}:{event.type}:{rule.id}"
            last = self._last_fired.get(dedup_key)
            if last and (now - last).total_seconds() < rule.cooldown_seconds:
                continue

            self._last_fired[dedup_key] = now

            alert = ActiveAlert(
                id=str(uuid.uuid4()),
                rule_id=rule.id,
                rule_name=rule.name,
                event=event,
                severity=event.severity,
                timestamp=now,
            )
            self._active_alerts.append(alert)
            logger.info("Alert fired: %s [%s] %s", rule.name, event.severity, event.message)

            # Send to notification channels
            for channel in self._channels:
                try:
                    await channel.send(alert, event)
                except Exception:
                    logger.exception("Notification channel error")

            # Auto-investigate urgent events
            if (
                rule.auto_investigate
                and event.severity == EventSeverity.URGENT
                and self._on_investigate
            ):
                try:
                    await self._on_investigate(event)
                except Exception:
                    logger.exception("Auto-investigation error for alert %s", alert.id)

    @staticmethod
    def _matches(rule: AlertRule, event: Event) -> bool:
        if event.type not in rule.event_types:
            return False
        severity_order = [EventSeverity.NORMAL, EventSeverity.NOTABLE, EventSeverity.URGENT]
        if severity_order.index(event.severity) < severity_order.index(rule.min_severity):
            return False
        return True

    def get_active_alerts(self, include_resolved: bool = False) -> list[ActiveAlert]:
        if include_resolved:
            return list(self._active_alerts)
        return [a for a in self._active_alerts if not a.resolved]

    def resolve_alert(self, alert_id: str) -> bool:
        for alert in self._active_alerts:
            if alert.id == alert_id and not alert.resolved:
                alert.resolved = True
                alert.resolved_at = datetime.now(UTC)
                return True
        return False
