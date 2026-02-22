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
async def test_alert_fires_on_matching_event(bus: EventBus, engine: AlertEngine):
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU at 99%",
    )
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

    # Different event type matching the same rule — also deduped
    mem_event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.MEMORY_HIGH,
        severity=EventSeverity.URGENT,
        message="Memory high",
    )
    await bus.publish(mem_event)

    assert len(engine.get_active_alerts()) == 1


@pytest.mark.asyncio
async def test_dedup_across_event_types(bus: EventBus):
    """CPU_HIGH then MEMORY_HIGH on the same rule produces only 1 alert."""
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
    assert len(alerts) == 1
    assert alerts[0].rule_name == "Resource Warning"


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
async def test_resolve_alert(bus: EventBus, engine: AlertEngine):
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
async def test_notification_channels_called(bus: EventBus, engine: AlertEngine):
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
    engine = AlertEngine(bus=bus, on_investigate=investigate_mock)
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
