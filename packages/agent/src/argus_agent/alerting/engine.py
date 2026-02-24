"""Smart alert engine with rule evaluation."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from argus_agent.agent.investigator import InvestigationRequest, InvestigationStatus
from argus_agent.events.bus import EventBus
from argus_agent.events.types import Event, EventSeverity, EventType

logger = logging.getLogger("argus.alerting.engine")

InvestigateCallback = Callable[[InvestigationRequest], InvestigationStatus]


class AlertState(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass
class AlertRule:
    """A rule that determines when an alert should fire."""

    id: str
    name: str
    event_types: list[str]
    min_severity: EventSeverity = EventSeverity.NOTABLE
    max_severity: EventSeverity | None = None
    cooldown_seconds: int = 300  # 5 min default
    auto_investigate: bool = False
    investigate_cooldown_seconds: int = 10800  # 3h default, independent of alert cooldown


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
    status: AlertState = AlertState.ACTIVE
    acknowledged_at: datetime | None = None
    acknowledged_by: str = ""


# Default rules
DEFAULT_RULES: list[AlertRule] = [
    AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=1800,
        auto_investigate=True,
    ),
    AlertRule(
        id="memory_critical",
        name="Memory Critical",
        event_types=[EventType.MEMORY_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=1800,
        auto_investigate=True,
    ),
    AlertRule(
        id="disk_critical",
        name="Disk Critical",
        event_types=[EventType.DISK_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=3600,
        auto_investigate=True,
    ),
    AlertRule(
        id="process_crash",
        name="Process Crash",
        event_types=[EventType.PROCESS_CRASHED, EventType.PROCESS_OOM_KILLED],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
        investigate_cooldown_seconds=3600,  # 1h — crashes are discrete events
    ),
    AlertRule(
        id="error_burst",
        name="Error Burst",
        event_types=[EventType.ERROR_BURST],
        min_severity=EventSeverity.NOTABLE,
        cooldown_seconds=600,
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
        cooldown_seconds=600,
        auto_investigate=True,
        investigate_cooldown_seconds=7200,  # 2h — security warrants more frequent checks
    ),
    AlertRule(
        id="resource_warning",
        name="Resource Warning",
        event_types=[
            EventType.CPU_HIGH, EventType.MEMORY_HIGH,
            EventType.DISK_HIGH, EventType.LOAD_HIGH,
        ],
        min_severity=EventSeverity.NOTABLE,
        max_severity=EventSeverity.NOTABLE,
        cooldown_seconds=1800,
        auto_investigate=False,
    ),
    AlertRule(
        id="anomaly",
        name="Anomaly Detected",
        event_types=[EventType.ANOMALY_DETECTED],
        min_severity=EventSeverity.NOTABLE,
        cooldown_seconds=1800,
        auto_investigate=True,
    ),
    AlertRule(
        id="sdk_error_spike",
        name="SDK Error Rate Spike",
        event_types=[EventType.SDK_ERROR_SPIKE],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=900,
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
    AlertRule(
        id="sdk_traffic_burst",
        name="Traffic Burst",
        event_types=[EventType.SDK_TRAFFIC_BURST],
        min_severity=EventSeverity.NOTABLE,
        cooldown_seconds=900,
        auto_investigate=True,
    ),
]


class AlertEngine:
    """Subscribes to the event bus and fires alerts based on rules.

    Features:
    - Rule-based matching on event type + severity
    - Deduplication with configurable cooldown per rule
    - Routes alerts to notification channels
    - Optional auto-investigation callback for urgent events
    - Suppression via acknowledgment (dedup_key level) and muting (rule level)
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
        self._formatter: Any = None  # AlertFormatter for external channels
        self._active_alerts: list[ActiveAlert] = []
        self._last_fired: dict[str, datetime] = {}  # dedup_key -> last fire time
        self._last_investigated: dict[str, datetime] = {}  # dedup_key -> last investigation time
        self._last_event_seen: dict[str, datetime] = {}  # dedup_key -> last matching event time
        # Suppression state
        self._acknowledged_keys: dict[str, datetime] = {}  # dedup_key -> expires_at
        self._muted_rules: dict[str, datetime] = {}  # rule_id -> expires_at

    def set_channels(self, channels: list[Any]) -> None:
        self._channels = channels

    def set_formatter(self, formatter: Any) -> None:
        self._formatter = formatter

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

    def _is_suppressed(
        self,
        dedup_key: str,
        rule_id: str,
        *,
        previous_seen: datetime | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Check if an alert should be suppressed via mute or acknowledgment.

        If *previous_seen* is provided and the gap since that timestamp exceeds
        the rule's cooldown, any acknowledgment for this dedup_key is auto-cleared
        (the condition resolved and a new incident started).
        """
        now = now or datetime.now(UTC)

        # Check rule-level mute first
        if rule_id in self._muted_rules:
            expires = self._muted_rules[rule_id]
            if now < expires:
                return True
            # Expired — clean up
            del self._muted_rules[rule_id]

        # Check dedup_key acknowledgment with gap detection
        if dedup_key in self._acknowledged_keys:
            # If there's a gap in events longer than the rule's cooldown,
            # the condition resolved — clear ack, this is a new incident
            if previous_seen is not None:
                rule = self._rules.get(rule_id)
                gap_threshold = rule.cooldown_seconds if rule else 300
                gap = (now - previous_seen).total_seconds()
                if gap > gap_threshold:
                    del self._acknowledged_keys[dedup_key]
                    logger.info(
                        "Ack auto-cleared for %s (event gap %.0fs > cooldown %ds)",
                        dedup_key, gap, gap_threshold,
                    )
                    return False

            # No gap (or first event) — check expiry
            ack_expires = self._acknowledged_keys[dedup_key]
            if now >= ack_expires:
                del self._acknowledged_keys[dedup_key]
                return False
            return True

        return False

    async def _handle_event(self, event: Event) -> None:
        """Evaluate all rules against an incoming event."""
        for rule in self._rules.values():
            if not self._matches(rule, event):
                continue

            now = datetime.now(UTC)
            dedup_key = f"{event.source}:{rule.id}"

            # Track when we last saw a matching event (even if suppressed)
            previous_seen = self._last_event_seen.get(dedup_key)
            self._last_event_seen[dedup_key] = now

            # Suppression check — before cooldown to short-circuit early
            if self._is_suppressed(dedup_key, rule.id, previous_seen=previous_seen, now=now):
                logger.debug("Alert suppressed for %s (acknowledged/muted)", dedup_key)
                continue

            # Dedup / cooldown
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

            # Persist to database
            try:
                from argus_agent.storage.alert_history import AlertHistoryService

                await AlertHistoryService().save(alert, event)
            except Exception:
                logger.exception("Failed to persist alert %s to database", alert.id)

            # Send to notification channels (WebSocket — immediate, unfiltered)
            for channel in self._channels:
                try:
                    await channel.send(alert, event)
                except Exception:
                    logger.exception("Notification channel error")

            # Route to formatter for external channels (severity-routed, batched)
            channel_metadata: dict[str, str] = {}
            if self._formatter is not None:
                try:
                    channel_metadata = await self._formatter.submit(alert, event)
                except Exception:
                    logger.exception("Formatter submit error")

            # Auto-investigate urgent events (with separate investigation cooldown)
            # Also gated behind suppression check
            if (
                rule.auto_investigate
                and event.severity == EventSeverity.URGENT
                and self._on_investigate
                and not self._is_suppressed(dedup_key, rule.id, now=now)
            ):
                invest_last = self._last_investigated.get(dedup_key)
                if (
                    invest_last
                    and (now - invest_last).total_seconds() < rule.investigate_cooldown_seconds
                ):
                    logger.info(
                        "Investigation cooldown active for %s, skipping re-investigation",
                        dedup_key,
                    )
                else:
                    try:
                        request = InvestigationRequest(
                            event=event,
                            alert_id=alert.id,
                            channel_metadata=channel_metadata,
                        )
                        self._on_investigate(request)
                        self._last_investigated[dedup_key] = now
                    except Exception:
                        logger.exception("Auto-investigation error for alert %s", alert.id)

    @staticmethod
    def _matches(rule: AlertRule, event: Event) -> bool:
        if event.type not in rule.event_types:
            return False
        severity_order = [EventSeverity.NORMAL, EventSeverity.NOTABLE, EventSeverity.URGENT]
        event_idx = severity_order.index(event.severity)
        if event_idx < severity_order.index(rule.min_severity):
            return False
        if rule.max_severity is not None:
            if event_idx > severity_order.index(rule.max_severity):
                return False
        return True

    def get_active_alerts(self, include_resolved: bool = False) -> list[ActiveAlert]:
        if include_resolved:
            return list(self._active_alerts)
        return [a for a in self._active_alerts if not a.resolved]

    def get_rules(self) -> dict[str, AlertRule]:
        """Return all alert rules."""
        return dict(self._rules)

    def resolve_alert(self, alert_id: str) -> bool:
        for alert in self._active_alerts:
            if alert.id == alert_id and not alert.resolved:
                alert.resolved = True
                alert.resolved_at = datetime.now(UTC)
                alert.status = AlertState.RESOLVED
                # Clear acknowledgment for this alert's dedup_key
                dedup_key = f"{alert.event.source}:{alert.rule_id}"
                self._acknowledged_keys.pop(dedup_key, None)
                return True
        return False

    def acknowledge_alert(
        self,
        alert_id: str,
        *,
        acknowledged_by: str = "user",
        expires_at: datetime | None = None,
    ) -> bool:
        """Acknowledge an alert and suppress its dedup_key.

        *expires_at* defaults to 24h from now as a safety cap.  Gap detection
        in ``_is_suppressed`` handles the normal "condition resolved" case;
        the 24h cap covers edge cases where events never resume.
        """
        from datetime import timedelta

        for alert in self._active_alerts:
            if alert.id == alert_id:
                now = datetime.now(UTC)
                alert.status = AlertState.ACKNOWLEDGED
                alert.acknowledged_at = now
                alert.acknowledged_by = acknowledged_by
                dedup_key = f"{alert.event.source}:{alert.rule_id}"
                # Always enforce a maximum expiry (24h safety cap)
                if expires_at is None:
                    expires_at = now + timedelta(hours=24)
                self._acknowledged_keys[dedup_key] = expires_at
                return True
        return False

    def unacknowledge_alert(self, alert_id: str) -> bool:
        """Remove acknowledgment from an alert."""
        for alert in self._active_alerts:
            if alert.id == alert_id and alert.status == AlertState.ACKNOWLEDGED:
                alert.status = AlertState.ACTIVE
                alert.acknowledged_at = None
                alert.acknowledged_by = ""
                dedup_key = f"{alert.event.source}:{alert.rule_id}"
                self._acknowledged_keys.pop(dedup_key, None)
                return True
        return False

    def mute_rule(self, rule_id: str, expires_at: datetime) -> bool:
        """Mute a rule until expires_at."""
        if rule_id not in self._rules:
            return False
        self._muted_rules[rule_id] = expires_at
        logger.info("Rule %s muted until %s", rule_id, expires_at.isoformat())
        return True

    def unmute_rule(self, rule_id: str) -> bool:
        """Unmute a rule."""
        if rule_id in self._muted_rules:
            del self._muted_rules[rule_id]
            logger.info("Rule %s unmuted", rule_id)
            return True
        return False

    def get_muted_rules(self) -> dict[str, datetime]:
        """Return currently muted rules (auto-expires stale entries)."""
        now = datetime.now(UTC)
        expired = [k for k, v in self._muted_rules.items() if now >= v]
        for k in expired:
            del self._muted_rules[k]
        return dict(self._muted_rules)

    def get_acknowledged_keys(self) -> dict[str, datetime]:
        """Return currently acknowledged dedup keys (auto-expires stale entries)."""
        now = datetime.now(UTC)
        expired = [k for k, v in self._acknowledged_keys.items() if now >= v]
        for k in expired:
            del self._acknowledged_keys[k]
        return dict(self._acknowledged_keys)
