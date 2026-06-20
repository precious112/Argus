"""Smart alert engine with rule evaluation."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from fastapi import HTTPException

from argus_agent.agent.investigator import InvestigationRequest, InvestigationStatus
from argus_agent.events.bus import EventBus
from argus_agent.events.types import Event, EventSeverity, EventType

logger = logging.getLogger("argus.alerting.engine")

InvestigateCallback = Callable[[InvestigationRequest], InvestigationStatus]

# How long a dedup_key must go without a matching event before its alert is
# considered recovered and auto-resolved. The effective threshold per alert is
# max(rule.cooldown_seconds, this floor).
_AUTO_RESOLVE_FLOOR_SECONDS = 300

# How long a resolved alert is kept in the in-memory list before being pruned.
# History lives in the database, so memory only needs recent context.
_RESOLVED_RETENTION_SECONDS = 3600


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
    for_seconds: int = 0  # breach must persist this long before firing (0 = fire immediately)
    renotify_seconds: int = 0  # re-notify an unacked, still-firing alert this often (0 = never)


@dataclass
class ActiveAlert:
    """An alert that has been triggered."""

    id: str
    rule_id: str
    rule_name: str
    event: Event
    severity: EventSeverity
    timestamp: datetime
    dedup_key: str = ""
    resolved: bool = False
    resolved_at: datetime | None = None
    status: AlertState = AlertState.ACTIVE
    acknowledged_at: datetime | None = None
    acknowledged_by: str = ""


def fingerprint_labels(labels: dict[str, str]) -> str:
    """Compute a stable fingerprint from sorted label key-value pairs.

    Follows Alertmanager's approach: identity = hash of all labels.
    """
    if not labels:
        return "nolabels"
    parts = sorted(labels.items())
    return ":".join(f"{k}={v}" for k, v in parts)


@dataclass
class Silence:
    """A time-bounded suppression rule matching alerts by label matchers.

    Modeled after Prometheus Alertmanager silences: a set of label matchers
    with an expiry. Not tied to a specific alert ID.
    """

    id: str
    matchers: dict[str, str]
    expires_at: datetime
    created_by: str = "user"
    reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


def build_dedup_key(event: Event, rule_id: str) -> str:
    """Build a context-aware dedup key from the finest distinguishing identity in each event.

    Instead of grouping all alerts of the same type under one key, this uses
    the most specific data available: error message for exceptions, name+pid
    for processes, ip/port for network events, service for SDK aggregates, etc.
    """
    data = event.data or {}
    msg = event.message or ""
    etype = event.type

    # --- Error / exception events ---
    # SDK error_burst: service + error message
    if etype == EventType.ERROR_BURST and event.source == "sdk_telemetry":
        service = data.get("service", "unknown")
        error_msg = data.get("message", msg).strip()
        return f"sdk_telemetry:error_burst:{service}:{error_msg}"

    # Log watcher error_burst: file + last error line
    if etype == EventType.ERROR_BURST:
        log_file = data.get("file", "unknown")
        last_error = data.get("last_error", msg).strip()
        return f"{event.source}:error_burst:{log_file}:{last_error}"

    # --- Security events ---
    if etype == EventType.SUSPICIOUS_PROCESS:
        name = data.get("name", "")
        pid = data.get("pid", "")
        if not name:
            m = re.search(r":\s*(\S+)", msg)
            name = m.group(1) if m else "unknown"
        if not pid:
            m = re.search(r"PID\s*(\d+)", msg)
            pid = m.group(1) if m else "unknown"
        return f"{event.source}:security_event:{name}:{pid}"

    if etype == EventType.BRUTE_FORCE:
        ip = data.get("ip", "")
        if not ip:
            m = re.search(r"from\s+(\S+)", msg)
            ip = m.group(1) if m else "unknown"
        return f"{event.source}:security_event:{ip}"

    if etype == EventType.SUSPICIOUS_OUTBOUND:
        ip = data.get("ip", "")
        port = data.get("port", "")
        if not ip:
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)", msg)
            ip = m.group(1) if m else "unknown"
        if not port:
            m = re.search(r":(\d+)", msg)
            port = m.group(1) if m else "unknown"
        return f"{event.source}:security_event:{ip}:{port}"

    if etype == EventType.NEW_EXECUTABLE:
        path = data.get("path", "")
        if not path:
            m = re.search(r":\s*(.+)", msg)
            path = m.group(1).strip() if m else "unknown"
        return f"{event.source}:security_event:{path}"

    if etype == EventType.NEW_OPEN_PORT:
        port = data.get("port", "")
        if not port:
            m = re.search(r"(\d+)", msg)
            port = m.group(1) if m else "unknown"
        return f"{event.source}:security_event:{port}"

    if etype == EventType.PERMISSION_RISK:
        path = data.get("path", "")
        if not path:
            m = re.search(r":\s*(\S+)", msg)
            path = m.group(1) if m else "unknown"
        return f"{event.source}:security_event:{path}"

    # --- Process events ---
    if etype in (EventType.PROCESS_CRASHED, EventType.PROCESS_OOM_KILLED):
        name = data.get("name", data.get("process_name", "unknown"))
        pid = data.get("pid", "unknown")
        return f"{event.source}:process_crash:{name}:{pid}"

    if etype == EventType.PROCESS_RESTART_LOOP:
        name = data.get("name", data.get("process_name", "unknown"))
        return f"{event.source}:process_crash:{name}"

    # --- Anomaly ---
    if etype == EventType.ANOMALY_DETECTED:
        metric = data.get("metric", "unknown")
        return f"{event.source}:anomaly_detected:{metric}"

    # --- SDK aggregate metric events (service is the lowest grain) ---
    if etype == EventType.SDK_ERROR_SPIKE:
        service = data.get("service", "unknown")
        return f"{event.source}:sdk_error_spike:{service}"

    if etype == EventType.SDK_LATENCY_DEGRADATION:
        service = data.get("service", "unknown")
        return f"{event.source}:sdk_latency:{service}"

    if etype == EventType.SDK_SERVICE_SILENT:
        service = data.get("service", "unknown")
        return f"{event.source}:sdk_service_silent:{service}"

    if etype == EventType.SDK_TRAFFIC_BURST:
        service = data.get("service", "unknown")
        return f"{event.source}:sdk_traffic_burst:{service}"

    if etype == EventType.SDK_METRIC_ANOMALY:
        service = data.get("service", "unknown")
        metric_name = data.get("metric_name", "unknown")
        return f"{event.source}:sdk_metric_anomaly:{service}:{metric_name}"

    if etype == EventType.SDK_COLD_START_SPIKE:
        service = data.get("service", "unknown")
        return f"{event.source}:sdk_cold_start:{service}"

    # --- System-wide metrics: key on event type so all severity rules share one key ---
    if etype in (EventType.CPU_HIGH, EventType.MEMORY_HIGH, EventType.DISK_HIGH):
        return f"{event.source}:{etype}"

    # Fallback: source + rule_id (preserves old behavior for unknown types)
    return f"{event.source}:{rule_id}"


# Default rules
DEFAULT_RULES: list[AlertRule] = [
    AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=1800,
        auto_investigate=True,
        for_seconds=120,  # only page if CPU stays critical for 2 min, not on a transient spike
        renotify_seconds=3600,  # remind hourly while it stays unacknowledged and firing
    ),
    AlertRule(
        id="memory_critical",
        name="Memory Critical",
        event_types=[EventType.MEMORY_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=1800,
        auto_investigate=True,
        for_seconds=120,  # ignore momentary memory spikes; require a 2 min sustained breach
        renotify_seconds=3600,
    ),
    AlertRule(
        id="disk_critical",
        name="Disk Critical",
        event_types=[EventType.DISK_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=3600,
        auto_investigate=True,
        for_seconds=180,  # disk fills gradually; require a 3 min sustained breach
        renotify_seconds=7200,  # disk pressure is slower-moving; remind every 2h
    ),
    AlertRule(
        id="process_crash",
        name="Process Crash",
        event_types=[EventType.PROCESS_CRASHED, EventType.PROCESS_OOM_KILLED],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
        investigate_cooldown_seconds=3600,  # 1h — crashes are discrete events
        renotify_seconds=3600,
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
        renotify_seconds=3600,
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
        for_seconds=120,  # don't alert on a single elevated sample; require it to persist
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
        renotify_seconds=3600,
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
        self._acknowledged_keys: dict[str, datetime] = {}  # dedup_key -> expires_at (legacy)
        self._muted_rules: dict[str, datetime] = {}  # rule_id -> expires_at
        self._silences: dict[str, Silence] = {}  # silence_id -> Silence
        # Duration gate: dedup_key -> first time the breach was seen (for_seconds rules)
        self._pending: dict[str, datetime] = {}
        # Re-notification: alert_id -> last time we notified channels about it
        self._last_notified: dict[str, datetime] = {}
        # Billing quota cache: tenant_id → (exceeded, expires_at)
        self._quota_cache: dict[str, tuple[bool, datetime]] = {}

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
        now = now or datetime.now(UTC).replace(tzinfo=None)

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

    def _is_silenced(
        self, labels: dict[str, str], rule_id: str, now: datetime | None = None,
    ) -> bool:
        """Check if a label set is silenced by any active silence.

        Modeled after Alertmanager: all matchers in a silence must match
        (AND logic). No gap detection — silences are purely time-bounded.
        """
        now = now or datetime.now(UTC).replace(tzinfo=None)

        # Check rule-level mute first
        if rule_id in self._muted_rules:
            expires = self._muted_rules[rule_id]
            if now < expires:
                return True
            del self._muted_rules[rule_id]

        # Check silences
        expired_ids = []
        for sid, silence in self._silences.items():
            if now >= silence.expires_at:
                expired_ids.append(sid)
                continue
            if all(labels.get(k) == v for k, v in silence.matchers.items()):
                return True
        for sid in expired_ids:
            del self._silences[sid]

        return False

    async def _is_over_quota(self, event: Event) -> bool:
        """Check if tenant is over event quota (cached per-tenant, 60s TTL)."""
        from argus_agent.config import get_settings

        if get_settings().deployment.mode != "saas":
            return False

        from argus_agent.tenancy.context import get_tenant_id

        tenant_id = (event.data or {}).get("tenant_id") or get_tenant_id()
        if tenant_id == "default":
            return False  # self-hosted or no tenant context — skip

        now = datetime.now(UTC).replace(tzinfo=None)
        cached = self._quota_cache.get(tenant_id)
        if cached and now < cached[1]:
            logger.info(
                "QUOTA_CHECK tenant=%s over=%s source=%s (cached)",
                tenant_id, cached[0], event.source,
            )
            return cached[0]

        try:
            from argus_agent.billing.usage_guard import check_event_ingest_limit

            await check_event_ingest_limit(tenant_id)
            self._quota_cache[tenant_id] = (False, now + timedelta(seconds=60))
            logger.info("QUOTA_CHECK tenant=%s over=False source=%s", tenant_id, event.source)
            return False
        except HTTPException:
            self._quota_cache[tenant_id] = (True, now + timedelta(seconds=60))
            logger.info("QUOTA_CHECK tenant=%s over=True source=%s", tenant_id, event.source)
            return True
        except Exception:
            self._quota_cache[tenant_id] = (False, now + timedelta(seconds=60))
            logger.info(
                "QUOTA_CHECK tenant=%s over=False source=%s (error-fallback)",
                tenant_id, event.source,
            )
            return False

    async def _increment_quota(self, event: Event) -> None:
        """Increment the unified event quota counter for this internal event."""
        try:
            from argus_agent.config import get_settings

            if get_settings().deployment.mode != "saas":
                return

            tenant_id = (event.data or {}).get("tenant_id")
            if not tenant_id:
                from argus_agent.tenancy.context import get_tenant_id

                tenant_id = get_tenant_id()
            if tenant_id == "default":
                return

            from argus_agent.billing.usage_guard import (
                _billing_period_start,
                _get_tenant_and_subscription,
            )
            from argus_agent.storage.repositories import get_metrics_repository

            _, sub = await _get_tenant_and_subscription(tenant_id)
            period_start = _billing_period_start(sub)
            repo = get_metrics_repository()
            repo.increment_event_quota(tenant_id, period_start, 1)
        except Exception:
            logger.debug("Failed to increment event quota for internal event", exc_info=True)

    async def _handle_event(self, event: Event) -> None:
        """Evaluate all rules against an incoming event."""
        # Restore tenant context from event data (events may arrive via Redis
        # or background tasks where the contextvar is not set)
        from argus_agent.tenancy.context import set_tenant_id

        tenant_id = (event.data or {}).get("tenant_id", "default")
        set_tenant_id(tenant_id)

        logger.info(
            "EVENT_RECEIVED source=%s type=%s severity=%s tenant=%s msg=%.100s",
            event.source, event.type, event.severity, tenant_id, event.message or "",
        )

        # In SaaS mode, suppress all alerts when over event quota
        if await self._is_over_quota(event):
            logger.warning(
                "EVENT_BLOCKED_QUOTA tenant=%s source=%s type=%s",
                tenant_id, event.source, event.type,
            )
            return

        fired = False  # Track whether any rule actually fires an alert

        for rule in self._rules.values():
            if not self._matches(rule, event):
                continue

            now = datetime.now(UTC).replace(tzinfo=None)

            # Label-based fingerprint when labels are populated;
            # fall back to legacy build_dedup_key for events without labels.
            if event.labels:
                dedup_key = fingerprint_labels(event.labels)
            else:
                dedup_key = build_dedup_key(event, rule.id)

            # Track when we last saw a matching event (even if suppressed)
            previous_seen = self._last_event_seen.get(dedup_key)
            self._last_event_seen[dedup_key] = now

            # Suppression check — silences for labeled events, legacy ack for unlabeled
            if event.labels:
                if self._is_silenced(event.labels, rule.id, now=now):
                    logger.debug("Alert silenced for %s", dedup_key)
                    continue
            elif self._is_suppressed(dedup_key, rule.id, previous_seen=previous_seen, now=now):
                logger.debug("Alert suppressed for %s (acknowledged/muted)", dedup_key)
                continue

            # Duration gate: require the breach to persist for `for_seconds` before the
            # first fire. Metrics are level-triggered, so a sustained breach keeps emitting
            # events that advance this pending timer; if the breach stops, events stop and
            # the auto-resolve sweep clears the stale pending entry. Cooldown (below) takes
            # over the anti-spam job once an alert has fired.
            if rule.for_seconds > 0:
                last_fired = self._last_fired.get(dedup_key)
                in_cooldown = (
                    last_fired is not None
                    and (now - last_fired).total_seconds() < rule.cooldown_seconds
                )
                if not in_cooldown:
                    first_breach = self._pending.get(dedup_key)
                    if first_breach is None:
                        self._pending[dedup_key] = now
                        logger.info(
                            "PENDING_ARMED dedup_key=%s rule=%s for=%ds",
                            dedup_key, rule.id, rule.for_seconds,
                        )
                        continue
                    if (now - first_breach).total_seconds() < rule.for_seconds:
                        logger.debug(
                            "PENDING dedup_key=%s elapsed=%.0fs need=%ds",
                            dedup_key, (now - first_breach).total_seconds(), rule.for_seconds,
                        )
                        continue
                    # Breach sustained long enough — clear pending so the gate re-arms
                    # for the next incident, then fall through to fire.
                    self._pending.pop(dedup_key, None)

            # Dedup / cooldown
            last = self._last_fired.get(dedup_key)
            if last and (now - last).total_seconds() < rule.cooldown_seconds:
                logger.info(
                    "COOLDOWN_ACTIVE dedup_key=%s rule=%s elapsed=%.0fs cooldown=%ds",
                    dedup_key, rule.id, (now - last).total_seconds(), rule.cooldown_seconds,
                )
                continue

            self._last_fired[dedup_key] = now

            alert = ActiveAlert(
                id=str(uuid.uuid4()),
                rule_id=rule.id,
                rule_name=rule.name,
                event=event,
                severity=event.severity,
                timestamp=now,
                dedup_key=dedup_key,
            )
            self._active_alerts.append(alert)
            fired = True
            logger.info("Alert fired: %s [%s] %s", rule.name, event.severity, event.message)
            logger.info(
                "ALERT_FIRED rule=%s dedup_key=%s severity=%s tenant=%s",
                rule.id, dedup_key, event.severity, tenant_id,
            )

            # Persist to database
            try:
                from argus_agent.storage.alert_history import AlertHistoryService

                await AlertHistoryService().save(alert, event)
            except Exception:
                logger.exception("Failed to persist alert %s to database", alert.id)

            # Reload channels for current tenant (SaaS: per-tenant Slack/Email)
            try:
                from argus_agent.alerting.reload import reload_channels

                await reload_channels()
            except Exception:
                logger.debug("Channel reload failed", exc_info=True)

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

            # Record initial notification time for re-notification scheduling.
            self._last_notified[alert.id] = now

            # Escalation contacts (SaaS, fire-and-forget)
            try:
                from argus_agent.alerting.escalation import notify_escalation_contacts

                asyncio.create_task(notify_escalation_contacts(alert, event))
            except Exception:
                logger.debug("Escalation notification skipped", exc_info=True)

            # Auto-investigate urgent events (with separate investigation cooldown)
            # Also gated behind suppression check
            suppressed_for_investigation = (
                self._is_silenced(event.labels, rule.id, now=now) if event.labels
                else self._is_suppressed(dedup_key, rule.id, now=now)
            )
            if (
                rule.auto_investigate
                and event.severity == EventSeverity.URGENT
                and self._on_investigate
                and not suppressed_for_investigation
            ):
                invest_last = self._last_investigated.get(dedup_key)
                if (
                    invest_last
                    and (now - invest_last).total_seconds() < rule.investigate_cooldown_seconds
                ):
                    elapsed = (now - invest_last).total_seconds()
                    logger.info(
                        "INVESTIGATION_COOLDOWN dedup_key=%s elapsed=%.0fs cooldown=%ds",
                        dedup_key, elapsed, rule.investigate_cooldown_seconds,
                    )
                else:
                    try:
                        request = InvestigationRequest(
                            event=event,
                            alert_id=alert.id,
                            channel_metadata=channel_metadata,
                            tenant_id=(event.data or {}).get("tenant_id", "default"),
                        )
                        self._on_investigate(request)
                        self._last_investigated[dedup_key] = now
                        logger.info(
                            "INVESTIGATION_TRIGGERED dedup_key=%s rule=%s tenant=%s",
                            dedup_key, rule.id, tenant_id,
                        )
                    except Exception:
                        logger.exception("Auto-investigation error for alert %s", alert.id)

        # Only count toward billing quota if at least one alert actually fired
        if fired:
            await self._increment_quota(event)

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
                now = datetime.now(UTC).replace(tzinfo=None)
                alert.resolved = True
                alert.resolved_at = now
                alert.status = AlertState.RESOLVED

                dedup_key = alert.dedup_key or build_dedup_key(alert.event, alert.rule_id)
                self._acknowledged_keys.pop(dedup_key, None)
                self._pending.pop(dedup_key, None)
                self._last_notified.pop(alert.id, None)

                # Grace-period silence: prevent immediate re-firing while condition clears
                if alert.event.labels:
                    rule = self._rules.get(alert.rule_id)
                    grace_seconds = (rule.cooldown_seconds * 2) if rule else 600
                    silence = Silence(
                        id=str(uuid.uuid4()),
                        matchers=dict(alert.event.labels),
                        expires_at=now + timedelta(seconds=grace_seconds),
                        created_by="system",
                        reason=f"Grace period after resolving {alert.rule_name}",
                    )
                    self._silences[silence.id] = silence

                return True
        return False

    async def auto_resolve_stale(self, now: datetime | None = None) -> int:
        """Auto-resolve alerts whose underlying condition has stopped firing.

        An alert's condition counts as "still active" as long as matching events
        keep arriving — they refresh ``_last_event_seen`` even while deduped within
        cooldown. When that stream goes quiet for longer than the rule's cooldown
        (floored at ``_AUTO_RESOLVE_FLOOR_SECONDS``), the condition has cleared, so
        the alert is resolved. Without this, alerts only ever resolve on a manual
        click and pile up as permanent "active" entries nobody clears. Runs
        periodically via the scheduler; also callable directly in tests.

        Unlike :meth:`resolve_alert`, this creates no grace-period silence — the
        condition has already been quiet, so there is nothing to debounce, and a
        genuine new breach should be free to fire immediately.

        Returns the number of alerts resolved.
        """
        now = now or datetime.now(UTC).replace(tzinfo=None)
        resolved = 0
        for alert in self._active_alerts:
            if alert.resolved:
                continue
            rule = self._rules.get(alert.rule_id)
            threshold = max(
                rule.cooldown_seconds if rule else 300,
                _AUTO_RESOLVE_FLOOR_SECONDS,
            )
            dedup_key = alert.dedup_key or build_dedup_key(alert.event, alert.rule_id)
            last_seen = self._last_event_seen.get(dedup_key, alert.timestamp)
            if (now - last_seen).total_seconds() <= threshold:
                continue

            alert.resolved = True
            alert.resolved_at = now
            alert.status = AlertState.RESOLVED
            self._acknowledged_keys.pop(dedup_key, None)
            self._pending.pop(dedup_key, None)
            self._last_notified.pop(alert.id, None)
            resolved += 1
            logger.info(
                "ALERT_AUTO_RESOLVED alert=%s rule=%s dedup_key=%s quiet_for=%.0fs",
                alert.id, alert.rule_id, dedup_key, (now - last_seen).total_seconds(),
            )

            # Persist resolution so it survives restarts and reflects in history.
            try:
                from argus_agent.storage.alert_history import AlertHistoryService

                await AlertHistoryService().update_status(
                    alert.id, status="resolved", resolved=True, resolved_at=now,
                )
            except Exception:
                logger.debug(
                    "Failed to persist auto-resolution for %s", alert.id, exc_info=True,
                )

        # Drop stale pending breaches whose event stream has gone quiet, so the
        # duration gate re-arms cleanly on the next incident (and memory stays bounded).
        for key, first_breach in list(self._pending.items()):
            last_seen = self._last_event_seen.get(key, first_breach)
            if (now - last_seen).total_seconds() > _AUTO_RESOLVE_FLOOR_SECONDS:
                del self._pending[key]

        # Bound the in-memory list: drop alerts that have been resolved longer than
        # the retention window. History lives in the database (AlertHistory), so the
        # in-memory list only needs recent + active alerts. Without this, _active_alerts
        # grows without bound over the lifetime of the process.
        if self._active_alerts:
            kept: list[ActiveAlert] = []
            for alert in self._active_alerts:
                if (
                    alert.resolved
                    and alert.resolved_at is not None
                    and (now - alert.resolved_at).total_seconds() > _RESOLVED_RETENTION_SECONDS
                ):
                    self._last_notified.pop(alert.id, None)
                    continue
                kept.append(alert)
            self._active_alerts = kept

        return resolved

    async def renotify_unacked(self, now: datetime | None = None) -> int:
        """Re-send notifications for alerts that are still firing and unacknowledged.

        Self-hosted has no escalation tiers, so an URGENT alert that nobody
        acknowledges would otherwise fire exactly once and be forgotten. This
        re-notifies on the rule's ``renotify_seconds`` cadence, but only while the
        condition is still active (matching events still arriving) — an alert whose
        condition has gone quiet is left for the auto-resolve sweep instead.

        Runs periodically via the scheduler. Returns the number re-notified.
        """
        now = now or datetime.now(UTC).replace(tzinfo=None)
        count = 0
        for alert in self._active_alerts:
            if alert.resolved or alert.status != AlertState.ACTIVE:
                continue
            rule = self._rules.get(alert.rule_id)
            if rule is None or rule.renotify_seconds <= 0:
                continue

            dedup_key = alert.dedup_key or build_dedup_key(alert.event, alert.rule_id)
            # Skip conditions that have gone quiet — the resolve sweep handles those.
            resolve_threshold = max(rule.cooldown_seconds, _AUTO_RESOLVE_FLOOR_SECONDS)
            last_seen = self._last_event_seen.get(dedup_key, alert.timestamp)
            if (now - last_seen).total_seconds() > resolve_threshold:
                continue

            last_notified = self._last_notified.get(alert.id, alert.timestamp)
            if (now - last_notified).total_seconds() < rule.renotify_seconds:
                continue

            await self._redispatch(alert)
            self._last_notified[alert.id] = now
            count += 1
            logger.info(
                "ALERT_RENOTIFIED alert=%s rule=%s dedup_key=%s",
                alert.id, alert.rule_id, dedup_key,
            )
        return count

    async def _redispatch(self, alert: ActiveAlert) -> None:
        """Re-send an existing alert to the notification channels (re-notification).

        Reuses the same channels + formatter as the initial fire, so re-notifications
        inherit reliable delivery. Does not re-persist, re-escalate, or re-investigate.
        """
        try:
            from argus_agent.alerting.reload import reload_channels

            await reload_channels()
        except Exception:
            logger.debug("Channel reload failed during renotify", exc_info=True)

        for channel in self._channels:
            try:
                await channel.send(alert, alert.event)
            except Exception:
                logger.exception("Renotify channel error")

        if self._formatter is not None:
            try:
                await self._formatter.submit(alert, alert.event)
            except Exception:
                logger.exception("Renotify formatter submit error")

    def acknowledge_alert(
        self,
        alert_id: str,
        *,
        acknowledged_by: str = "user",
        expires_at: datetime | None = None,
    ) -> bool:
        """Acknowledge an alert by creating a silence from its labels.

        For labeled events, creates a Silence (time-bounded, no gap detection).
        Falls back to legacy dedup_key ack for unlabeled events.
        """
        for alert in self._active_alerts:
            if alert.id == alert_id:
                now = datetime.now(UTC).replace(tzinfo=None)
                alert.status = AlertState.ACKNOWLEDGED
                alert.acknowledged_at = now
                alert.acknowledged_by = acknowledged_by

                if expires_at is None:
                    expires_at = now + timedelta(hours=24)

                if alert.event.labels:
                    silence = Silence(
                        id=str(uuid.uuid4()),
                        matchers=dict(alert.event.labels),
                        expires_at=expires_at,
                        created_by=acknowledged_by,
                        reason=f"Acknowledged alert {alert.rule_name}",
                    )
                    self._silences[silence.id] = silence
                else:
                    dedup_key = alert.dedup_key or build_dedup_key(alert.event, alert.rule_id)
                    self._acknowledged_keys[dedup_key] = expires_at
                return True
        return False

    def unacknowledge_alert(self, alert_id: str) -> bool:
        """Remove acknowledgment from an alert.

        For labeled events, removes any silence whose matchers exactly match
        the alert's labels. Falls back to legacy dedup_key removal.
        """
        for alert in self._active_alerts:
            if alert.id == alert_id and alert.status == AlertState.ACKNOWLEDGED:
                alert.status = AlertState.ACTIVE
                alert.acknowledged_at = None
                alert.acknowledged_by = ""

                if alert.event.labels:
                    to_remove = [
                        sid for sid, s in self._silences.items()
                        if s.matchers == alert.event.labels and s.created_by != "system"
                    ]
                    for sid in to_remove:
                        del self._silences[sid]
                else:
                    dedup_key = alert.dedup_key or build_dedup_key(alert.event, alert.rule_id)
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
        now = datetime.now(UTC).replace(tzinfo=None)
        expired = [k for k, v in self._muted_rules.items() if now >= v]
        for k in expired:
            del self._muted_rules[k]
        return dict(self._muted_rules)

    def get_acknowledged_keys(self) -> dict[str, datetime]:
        """Return currently acknowledged dedup keys (auto-expires stale entries)."""
        now = datetime.now(UTC).replace(tzinfo=None)
        expired = [k for k, v in self._acknowledged_keys.items() if now >= v]
        for k in expired:
            del self._acknowledged_keys[k]
        return dict(self._acknowledged_keys)

    def get_silences(self) -> list[dict[str, Any]]:
        """Return active silences, auto-expiring stale ones."""
        now = datetime.now(UTC).replace(tzinfo=None)
        expired = [sid for sid, s in self._silences.items() if now >= s.expires_at]
        for sid in expired:
            del self._silences[sid]
        return [
            {
                "id": s.id,
                "matchers": s.matchers,
                "expires_at": s.expires_at.isoformat(),
                "created_by": s.created_by,
                "reason": s.reason,
                "created_at": s.created_at.isoformat(),
            }
            for s in self._silences.values()
        ]

    def add_silence(self, silence: Silence) -> None:
        """Add a silence (used by suppression service on startup load)."""
        self._silences[silence.id] = silence

    def remove_silence_by_matchers(self, matchers: dict[str, str]) -> bool:
        """Remove silences matching the given matchers exactly."""
        to_remove = [
            sid for sid, s in self._silences.items()
            if s.matchers == matchers and s.created_by != "system"
        ]
        for sid in to_remove:
            del self._silences[sid]
        return len(to_remove) > 0
