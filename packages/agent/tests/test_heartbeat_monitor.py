"""Tests for the persistent HeartbeatMonitor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.collectors.heartbeat_monitor import HeartbeatMonitor
from argus_agent.events.types import EventType


def _summaries(*services: str) -> list[dict]:
    """Build fake query_service_summary output."""
    return [{"service": s, "invocation_count": 10} for s in services]


@pytest.mark.asyncio
async def test_seed_populates_known_services():
    """On first check, the monitor should seed known_services from DB."""
    mon = HeartbeatMonitor(interval=60, silence_threshold=300)
    mock_query = MagicMock(return_value=_summaries("svc-a", "svc-b"))

    with patch(
        "argus_agent.collectors.heartbeat_monitor.get_event_bus",
        return_value=MagicMock(publish=AsyncMock()),
    ):
        await mon._seed(mock_query)

    assert "svc-a" in mon._known_services
    assert "svc-b" in mon._known_services
    assert mon._seeded is False  # _seed doesn't set this; _check does


@pytest.mark.asyncio
async def test_silent_service_detected():
    """A service that was known but stops reporting should trigger SILENT event."""
    mon = HeartbeatMonitor(interval=60, silence_threshold=60)
    # Pre-seed: svc-a was seen 2 minutes ago
    now = datetime.now(UTC).replace(tzinfo=None)
    mon._known_services = {"svc-a": now - timedelta(seconds=120)}
    mon._seeded = True

    mock_bus = MagicMock(publish=AsyncMock())

    with (
        patch(
            "argus_agent.storage.timeseries.query_service_summary",
            return_value=[],  # svc-a no longer reporting
        ),
        patch(
            "argus_agent.collectors.heartbeat_monitor.get_event_bus",
            return_value=mock_bus,
        ),
    ):
        await mon._check()

    assert "svc-a" in mon._silent_services
    mock_bus.publish.assert_called_once()
    event = mock_bus.publish.call_args[0][0]
    assert event.type == EventType.SDK_SERVICE_SILENT
    assert event.data["service"] == "svc-a"


@pytest.mark.asyncio
async def test_recovered_service_detected():
    """A silent service that comes back should trigger RECOVERED event."""
    mon = HeartbeatMonitor(interval=60, silence_threshold=60)
    now = datetime.now(UTC).replace(tzinfo=None)
    mon._known_services = {"svc-a": now - timedelta(seconds=120)}
    mon._silent_services = {"svc-a"}
    mon._seeded = True

    mock_bus = MagicMock(publish=AsyncMock())

    with (
        patch(
            "argus_agent.storage.timeseries.query_service_summary",
            return_value=_summaries("svc-a"),
        ),
        patch(
            "argus_agent.collectors.heartbeat_monitor.get_event_bus",
            return_value=mock_bus,
        ),
    ):
        await mon._check()

    assert "svc-a" not in mon._silent_services
    mock_bus.publish.assert_called_once()
    event = mock_bus.publish.call_args[0][0]
    assert event.type == EventType.SDK_SERVICE_RECOVERED
    assert event.data["service"] == "svc-a"


@pytest.mark.asyncio
async def test_active_service_not_alerted():
    """A service that is still active should not trigger any alert."""
    mon = HeartbeatMonitor(interval=60, silence_threshold=300)
    now = datetime.now(UTC).replace(tzinfo=None)
    mon._known_services = {"svc-a": now}
    mon._seeded = True

    mock_bus = MagicMock(publish=AsyncMock())

    with (
        patch(
            "argus_agent.storage.timeseries.query_service_summary",
            return_value=_summaries("svc-a"),
        ),
        patch(
            "argus_agent.collectors.heartbeat_monitor.get_event_bus",
            return_value=mock_bus,
        ),
    ):
        await mon._check()

    mock_bus.publish.assert_not_called()
    assert "svc-a" not in mon._silent_services


@pytest.mark.asyncio
async def test_first_check_seeds_and_skips_alerting():
    """The very first _check() should seed from DB and not alert."""
    mon = HeartbeatMonitor(interval=60, silence_threshold=60)
    assert not mon._seeded

    mock_bus = MagicMock(publish=AsyncMock())

    with (
        patch(
            "argus_agent.storage.timeseries.query_service_summary",
            return_value=_summaries("svc-a"),
        ),
        patch(
            "argus_agent.collectors.heartbeat_monitor.get_event_bus",
            return_value=mock_bus,
        ),
    ):
        await mon._check()

    assert mon._seeded is True
    assert "svc-a" in mon._known_services
    # No alert on first tick
    mock_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_already_silent_not_re_alerted():
    """A service already marked silent should not trigger a second SILENT event."""
    mon = HeartbeatMonitor(interval=60, silence_threshold=60)
    now = datetime.now(UTC).replace(tzinfo=None)
    mon._known_services = {"svc-a": now - timedelta(seconds=120)}
    mon._silent_services = {"svc-a"}  # already alerted
    mon._seeded = True

    mock_bus = MagicMock(publish=AsyncMock())

    with (
        patch(
            "argus_agent.storage.timeseries.query_service_summary",
            return_value=[],
        ),
        patch(
            "argus_agent.collectors.heartbeat_monitor.get_event_bus",
            return_value=mock_bus,
        ),
    ):
        await mon._check()

    mock_bus.publish.assert_not_called()
