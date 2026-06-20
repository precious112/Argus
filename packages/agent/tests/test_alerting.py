"""Tests for the alert engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.agent.investigator import InvestigationRequest
from argus_agent.alerting.engine import AlertEngine, AlertRule
from argus_agent.events.bus import EventBus
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def engine(bus):
    return AlertEngine(bus=bus)


@pytest.mark.asyncio
async def test_alert_fires_after_sustained_breach(bus: EventBus, engine: AlertEngine):
    """The default CPU rule has a duration gate: a single sample arms the timer,
    and the alert only fires once the breach persists past `for_seconds`."""
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU at 99%",
    )

    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=121)  # past cpu_critical for_seconds (120s)

    with patch("argus_agent.alerting.engine.datetime") as mock_dt:
        mock_dt.now.return_value = t1
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await bus.publish(event)
        # First sample only arms the pending timer — no alert yet.
        assert len(engine.get_active_alerts()) == 0

        mock_dt.now.return_value = t2
        await bus.publish(event)

    alerts = engine.get_active_alerts()
    assert len(alerts) == 1
    assert alerts[0].rule_name == "CPU Critical"
    assert alerts[0].severity == EventSeverity.URGENT


@pytest.mark.asyncio
async def test_no_alert_for_normal_severity(bus: EventBus, engine: AlertEngine):
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.NORMAL,
        message="CPU normal",
    )
    await bus.publish(event)

    assert len(engine.get_active_alerts()) == 0


@pytest.mark.asyncio
async def test_no_alert_for_unmatched_event_type(bus: EventBus, engine: AlertEngine):
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.METRIC_COLLECTED,
        severity=EventSeverity.URGENT,
        message="Just a collection",
    )
    await bus.publish(event)

    assert len(engine.get_active_alerts()) == 0


@pytest.mark.asyncio
async def test_dedup_within_cooldown(bus: EventBus):
    rule = AlertRule(
        id="test_rule",
        name="Test",
        event_types=[EventType.CPU_HIGH, EventType.MEMORY_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)
    await bus.publish(event)  # same type — should be deduped

    # Same event type again — still deduped
    assert len(engine.get_active_alerts()) == 1

    # Different event type produces a separate alert (different dedup key)
    mem_event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.MEMORY_HIGH,
        severity=EventSeverity.URGENT,
        message="Memory high",
    )
    await bus.publish(mem_event)

    assert len(engine.get_active_alerts()) == 2


@pytest.mark.asyncio
async def test_dedup_across_event_types(bus: EventBus):
    """CPU_HIGH then MEMORY_HIGH produce separate alerts (different dedup keys).

    System metric events are keyed by event type so that acknowledging
    CPU_HIGH doesn't suppress MEMORY_HIGH, even under the same rule.
    """
    rule = AlertRule(
        id="resource_warning",
        name="Resource Warning",
        event_types=[EventType.CPU_HIGH, EventType.MEMORY_HIGH,
                     EventType.DISK_HIGH, EventType.LOAD_HIGH],
        min_severity=EventSeverity.NOTABLE,
        cooldown_seconds=1800,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    cpu_event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.NOTABLE,
        message="CPU at 80%",
    )
    mem_event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.MEMORY_HIGH,
        severity=EventSeverity.NOTABLE,
        message="Memory at 85%",
    )

    await bus.publish(cpu_event)
    await bus.publish(mem_event)

    alerts = engine.get_active_alerts()
    assert len(alerts) == 2

    # Duplicate CPU_HIGH is still deduped within cooldown
    await bus.publish(cpu_event)
    assert len(engine.get_active_alerts()) == 2


@pytest.mark.asyncio
async def test_dedup_expires_after_cooldown(bus: EventBus):
    rule = AlertRule(
        id="test_rule",
        name="Test",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=60,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )

    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=61)

    with patch("argus_agent.alerting.engine.datetime") as mock_dt:
        mock_dt.now.return_value = t1
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await bus.publish(event)

        mock_dt.now.return_value = t2
        await bus.publish(event)

    assert len(engine.get_active_alerts()) == 2


@pytest.mark.asyncio
async def test_resolve_alert(bus: EventBus):
    # Immediate-fire rule (for_seconds defaults to 0) keeps this focused on resolve.
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)

    alerts = engine.get_active_alerts()
    assert len(alerts) == 1

    result = engine.resolve_alert(alerts[0].id)
    assert result is True
    assert len(engine.get_active_alerts()) == 0
    assert len(engine.get_active_alerts(include_resolved=True)) == 1


@pytest.mark.asyncio
async def test_resolve_nonexistent_alert(engine: AlertEngine):
    assert engine.resolve_alert("nonexistent") is False


@pytest.mark.asyncio
async def test_notification_channels_called(bus: EventBus):
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    mock_channel = AsyncMock()
    mock_channel.send = AsyncMock(return_value=True)
    engine.set_channels([mock_channel])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)

    mock_channel.send.assert_called_once()


@pytest.mark.asyncio
async def test_auto_investigate_on_urgent(bus: EventBus):
    investigate_mock = MagicMock()
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        auto_investigate=True,
    )
    engine = AlertEngine(bus=bus, rules=[rule], on_investigate=investigate_mock)
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU critical",
    )
    await bus.publish(event)

    investigate_mock.assert_called_once()
    call_args = investigate_mock.call_args[0][0]
    assert isinstance(call_args, InvestigationRequest)
    assert call_args.event == event


@pytest.mark.asyncio
async def test_no_auto_investigate_on_notable(bus: EventBus):
    investigate_mock = MagicMock()
    engine = AlertEngine(bus=bus, on_investigate=investigate_mock)
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.ANOMALY_DETECTED,
        severity=EventSeverity.NOTABLE,
        message="Anomaly found",
    )
    await bus.publish(event)

    investigate_mock.assert_not_called()


@pytest.mark.asyncio
async def test_security_event_alert(bus: EventBus, engine: AlertEngine):
    await engine.start()

    event = Event(
        source=EventSource.SECURITY_SCANNER,
        type=EventType.BRUTE_FORCE,
        severity=EventSeverity.URGENT,
        message="SSH brute force detected",
    )
    await bus.publish(event)

    alerts = engine.get_active_alerts()
    assert len(alerts) == 1
    assert alerts[0].rule_name == "Security Event"


@pytest.mark.asyncio
async def test_severity_filtering():
    """NOTABLE event doesn't match a rule with min_severity=URGENT."""
    rule = AlertRule(
        id="urgent_only",
        name="Urgent Only",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
    )
    bus = EventBus()
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.NOTABLE,
        message="CPU somewhat high",
    )
    await bus.publish(event)

    assert len(engine.get_active_alerts()) == 0


@pytest.mark.asyncio
async def test_investigation_cooldown_suppresses_reinvestigation(bus: EventBus):
    """Two URGENT events within investigation cooldown: investigate once, alert twice."""
    investigate_mock = MagicMock()
    rule = AlertRule(
        id="test_rule",
        name="Test",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=60,
        auto_investigate=True,
        investigate_cooldown_seconds=3600,
    )
    engine = AlertEngine(bus=bus, rules=[rule], on_investigate=investigate_mock)
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU critical",
    )

    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=120)  # past alert cooldown, within investigation cooldown

    with patch("argus_agent.alerting.engine.datetime") as mock_dt:
        mock_dt.now.return_value = t1
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await bus.publish(event)

        mock_dt.now.return_value = t2
        await bus.publish(event)

    assert len(engine.get_active_alerts()) == 2  # both alerts fired
    investigate_mock.assert_called_once()  # investigation only once


@pytest.mark.asyncio
async def test_investigation_cooldown_expires(bus: EventBus):
    """After investigation cooldown expires, a new investigation is triggered."""
    investigate_mock = MagicMock()
    rule = AlertRule(
        id="test_rule",
        name="Test",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=60,
        auto_investigate=True,
        investigate_cooldown_seconds=3600,
    )
    engine = AlertEngine(bus=bus, rules=[rule], on_investigate=investigate_mock)
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU critical",
    )

    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=3601)  # past both cooldowns

    with patch("argus_agent.alerting.engine.datetime") as mock_dt:
        mock_dt.now.return_value = t1
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await bus.publish(event)

        mock_dt.now.return_value = t2
        await bus.publish(event)

    assert len(engine.get_active_alerts()) == 2
    assert investigate_mock.call_count == 2  # investigated both times


@pytest.mark.asyncio
async def test_investigation_cooldown_independent_of_alert_cooldown(bus: EventBus):
    """Short alert cooldown + long investigation cooldown: alert re-fires, investigation doesn't."""
    investigate_mock = MagicMock()
    rule = AlertRule(
        id="test_rule",
        name="Test",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=60,
        auto_investigate=True,
        investigate_cooldown_seconds=3600,
    )
    engine = AlertEngine(bus=bus, rules=[rule], on_investigate=investigate_mock)
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU critical",
    )

    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=120)   # past alert cooldown (60s)
    t3 = t1 + timedelta(seconds=300)   # still within investigation cooldown (3600s)

    with patch("argus_agent.alerting.engine.datetime") as mock_dt:
        mock_dt.now.return_value = t1
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await bus.publish(event)

        mock_dt.now.return_value = t2
        await bus.publish(event)

        mock_dt.now.return_value = t3
        await bus.publish(event)

    assert len(engine.get_active_alerts()) == 3  # all three alerts fired
    investigate_mock.assert_called_once()  # investigation only on the first


# --- Duration gate (for_seconds) ---------------------------------------------


@pytest.mark.asyncio
async def test_duration_gate_suppresses_single_sample(bus: EventBus):
    """A breach that does not persist for `for_seconds` never fires."""
    rule = AlertRule(
        id="test_rule",
        name="Test",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
        for_seconds=120,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )

    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=121)

    with patch("argus_agent.alerting.engine.datetime") as mock_dt:
        mock_dt.now.return_value = t1
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await bus.publish(event)
        # Only armed the pending timer — nothing fires yet.
        assert len(engine.get_active_alerts()) == 0
        assert engine._pending  # pending timer is set

        mock_dt.now.return_value = t2
        await bus.publish(event)

    assert len(engine.get_active_alerts()) == 1
    assert engine._pending == {}  # cleared on fire


@pytest.mark.asyncio
async def test_duration_gate_resets_when_breach_stops(bus: EventBus):
    """If the breach stops before `for_seconds`, the stale pending timer is cleared
    by the auto-resolve sweep and no alert fires."""
    rule = AlertRule(
        id="test_rule",
        name="Test",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
        for_seconds=120,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )

    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

    with patch("argus_agent.alerting.engine.datetime") as mock_dt:
        mock_dt.now.return_value = t1
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await bus.publish(event)  # arms pending
        assert engine._pending

    # Breach goes quiet; sweep well past the floor clears the pending timer.
    cleared = t1.replace(tzinfo=None) + timedelta(seconds=400)
    await engine.auto_resolve_stale(now=cleared)
    assert engine._pending == {}
    assert len(engine.get_active_alerts()) == 0


# --- Auto-resolution ----------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_resolve_when_condition_clears(bus: EventBus):
    """An active alert is auto-resolved once its condition stops producing events."""
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)
    assert len(engine.get_active_alerts()) == 1

    # No further events; a sweep past the threshold treats the condition as cleared.
    future = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=400)
    resolved = await engine.auto_resolve_stale(now=future)

    assert resolved == 1
    assert len(engine.get_active_alerts()) == 0
    assert len(engine.get_active_alerts(include_resolved=True)) == 1


@pytest.mark.asyncio
async def test_auto_resolve_keeps_alert_while_breaching(bus: EventBus):
    """An alert stays active while matching events keep arriving (within threshold)."""
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)

    # Sweep shortly after firing — within the threshold, so the alert stays active.
    soon = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=100)
    resolved = await engine.auto_resolve_stale(now=soon)

    assert resolved == 0
    assert len(engine.get_active_alerts()) == 1


@pytest.mark.asyncio
async def test_resolved_alerts_pruned_from_memory(bus: EventBus):
    """Resolved alerts older than the retention window are dropped from memory."""
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)
    alert_id = engine.get_active_alerts()[0].id
    engine.resolve_alert(alert_id)
    assert len(engine.get_active_alerts(include_resolved=True)) == 1

    # Sweep far past the retention window — the resolved alert is pruned.
    far = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=4000)
    await engine.auto_resolve_stale(now=far)
    assert len(engine.get_active_alerts(include_resolved=True)) == 0


# --- Re-notification ----------------------------------------------------------


@pytest.mark.asyncio
async def test_renotify_unacked_while_firing(bus: EventBus):
    """An unacked, still-firing alert is re-notified once its interval elapses."""
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
        renotify_seconds=600,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    mock_channel = AsyncMock()
    mock_channel.send = AsyncMock(return_value=True)
    engine.set_channels([mock_channel])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)
    assert mock_channel.send.call_count == 1  # initial notification

    from argus_agent.alerting.engine import build_dedup_key

    dedup_key = build_dedup_key(event, "cpu_critical")
    now0 = datetime.now(UTC).replace(tzinfo=None)

    # Before the interval elapses — no re-notification.
    await engine.renotify_unacked(now=now0 + timedelta(seconds=120))
    assert mock_channel.send.call_count == 1

    # Interval elapsed and condition still firing (recent event) — re-notify once.
    future = now0 + timedelta(seconds=700)
    engine._last_event_seen[dedup_key] = future
    n = await engine.renotify_unacked(now=future)
    assert n == 1
    assert mock_channel.send.call_count == 2


@pytest.mark.asyncio
async def test_no_renotify_when_acknowledged(bus: EventBus):
    """An acknowledged alert is not re-notified."""
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
        renotify_seconds=600,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    mock_channel = AsyncMock()
    mock_channel.send = AsyncMock(return_value=True)
    engine.set_channels([mock_channel])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)
    alert_id = engine.get_active_alerts()[0].id
    engine.acknowledge_alert(alert_id, acknowledged_by="user")

    from argus_agent.alerting.engine import build_dedup_key

    dedup_key = build_dedup_key(event, "cpu_critical")
    future = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=700)
    engine._last_event_seen[dedup_key] = future

    n = await engine.renotify_unacked(now=future)
    assert n == 0
    assert mock_channel.send.call_count == 1  # only the initial send


@pytest.mark.asyncio
async def test_no_renotify_when_condition_quiet(bus: EventBus):
    """A still-unacked alert whose condition went quiet is not re-notified
    (it will be auto-resolved instead)."""
    rule = AlertRule(
        id="cpu_critical",
        name="CPU Critical",
        event_types=[EventType.CPU_HIGH],
        min_severity=EventSeverity.URGENT,
        cooldown_seconds=300,
        renotify_seconds=600,
    )
    engine = AlertEngine(bus=bus, rules=[rule])
    mock_channel = AsyncMock()
    mock_channel.send = AsyncMock(return_value=True)
    engine.set_channels([mock_channel])
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU high",
    )
    await bus.publish(event)

    # Interval elapsed but no recent events (condition cleared) — no re-notify.
    future = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=700)
    n = await engine.renotify_unacked(now=future)
    assert n == 0
    assert mock_channel.send.call_count == 1
