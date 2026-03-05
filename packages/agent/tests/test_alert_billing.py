"""Tests for billing-aware alert suppression in the alert engine."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from argus_agent.alerting.engine import AlertEngine, AlertRule
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType


def _make_event(severity: EventSeverity = EventSeverity.NOTABLE) -> Event:
    return Event(
        source=EventSource.SDK_TELEMETRY,
        type=EventType.SDK_ERROR_SPIKE,
        severity=severity,
        message="test error spike",
        data={"service": "test-svc"},
    )


def _make_engine() -> AlertEngine:
    rules = [
        AlertRule(
            id="sdk_error_spike",
            name="SDK Error Rate Spike",
            event_types=[EventType.SDK_ERROR_SPIKE],
            min_severity=EventSeverity.NOTABLE,
            cooldown_seconds=0,  # no cooldown for testing
        ),
    ]
    return AlertEngine(rules=rules)


@pytest.mark.asyncio
async def test_notable_suppressed_when_over_quota():
    """Non-URGENT events should be suppressed when tenant is over quota."""
    engine = _make_engine()

    with patch.object(engine, "_is_over_quota", new_callable=AsyncMock, return_value=True):
        event = _make_event(EventSeverity.NOTABLE)
        await engine._handle_event(event)

    assert len(engine.get_active_alerts()) == 0


@pytest.mark.asyncio
async def test_urgent_suppressed_when_over_quota():
    """ALL events (including URGENT) should be suppressed when over quota."""
    engine = _make_engine()

    with patch.object(engine, "_is_over_quota", new_callable=AsyncMock, return_value=True):
        event = _make_event(EventSeverity.URGENT)
        await engine._handle_event(event)

    assert len(engine.get_active_alerts()) == 0


@pytest.mark.asyncio
async def test_all_events_fire_when_under_quota():
    """All events should fire normally when under quota."""
    engine = _make_engine()

    with patch.object(engine, "_is_over_quota", new_callable=AsyncMock, return_value=False):
        await engine._handle_event(_make_event(EventSeverity.NOTABLE))
        await engine._handle_event(_make_event(EventSeverity.URGENT))

    assert len(engine.get_active_alerts()) == 2


@pytest.mark.asyncio
async def test_self_hosted_unaffected():
    """Self-hosted mode should never suppress alerts via quota."""
    engine = _make_engine()

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "self_hosted"
        result = await engine._is_over_quota()

    assert result is False


@pytest.mark.asyncio
async def test_quota_check_cached():
    """Quota result should be cached for 60s."""
    engine = _make_engine()

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "saas"

        with patch(
            "argus_agent.billing.usage_guard.check_event_ingest_limit",
            new_callable=AsyncMock,
        ) as mock_check:
            from fastapi import HTTPException

            mock_check.side_effect = HTTPException(status_code=429, detail="over limit")

            with patch("argus_agent.tenancy.context.get_tenant_id", return_value="t1"):
                result1 = await engine._is_over_quota()
                assert result1 is True
                assert mock_check.call_count == 1

                # Second call should use cache
                result2 = await engine._is_over_quota()
                assert result2 is True
                assert mock_check.call_count == 1  # not called again


@pytest.mark.asyncio
async def test_quota_cache_expires():
    """Cache should expire after TTL."""
    engine = _make_engine()
    # Manually set an expired cache
    engine._quota_exceeded_cache = True
    engine._quota_cache_expires = datetime(2000, 1, 1)  # long expired

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "saas"

        with patch(
            "argus_agent.billing.usage_guard.check_event_ingest_limit",
            new_callable=AsyncMock,
        ):
            with patch("argus_agent.tenancy.context.get_tenant_id", return_value="t1"):
                result = await engine._is_over_quota()

    # check_event_ingest_limit didn't raise → not over quota
    assert result is False
