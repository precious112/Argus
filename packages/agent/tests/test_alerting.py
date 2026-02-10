"""Tests for the alert engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

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
    await bus.publish(event)  # should be deduped

    assert len(engine.get_active_alerts()) == 1


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
    investigate_mock = AsyncMock()
    engine = AlertEngine(bus=bus, on_investigate=investigate_mock)
    await engine.start()

    event = Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message="CPU critical",
    )
    await bus.publish(event)

    investigate_mock.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_no_auto_investigate_on_notable(bus: EventBus):
    investigate_mock = AsyncMock()
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
