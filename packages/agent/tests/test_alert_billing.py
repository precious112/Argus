"""Tests for billing-aware alert suppression and unified quota in the alert engine."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.alerting.engine import AlertEngine, AlertRule
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType


def _make_event(
    severity: EventSeverity = EventSeverity.NOTABLE,
    tenant_id: str = "t1",
) -> Event:
    return Event(
        source=EventSource.SDK_TELEMETRY,
        type=EventType.SDK_ERROR_SPIKE,
        severity=severity,
        message="test error spike",
        data={"service": "test-svc", "tenant_id": tenant_id},
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

    with (
        patch.object(engine, "_is_over_quota", new_callable=AsyncMock, return_value=True),
        patch.object(engine, "_increment_quota", new_callable=AsyncMock),
    ):
        event = _make_event(EventSeverity.NOTABLE)
        await engine._handle_event(event)

    assert len(engine.get_active_alerts()) == 0


@pytest.mark.asyncio
async def test_urgent_suppressed_when_over_quota():
    """ALL events (including URGENT) should be suppressed when over quota."""
    engine = _make_engine()

    with (
        patch.object(engine, "_is_over_quota", new_callable=AsyncMock, return_value=True),
        patch.object(engine, "_increment_quota", new_callable=AsyncMock),
    ):
        event = _make_event(EventSeverity.URGENT)
        await engine._handle_event(event)

    assert len(engine.get_active_alerts()) == 0


@pytest.mark.asyncio
async def test_all_events_fire_when_under_quota():
    """All events should fire normally when under quota."""
    engine = _make_engine()

    with (
        patch.object(engine, "_is_over_quota", new_callable=AsyncMock, return_value=False),
        patch.object(engine, "_increment_quota", new_callable=AsyncMock),
    ):
        await engine._handle_event(_make_event(EventSeverity.NOTABLE))
        await engine._handle_event(_make_event(EventSeverity.URGENT))

    assert len(engine.get_active_alerts()) == 2


@pytest.mark.asyncio
async def test_handle_event_calls_increment_quota():
    """_handle_event should call _increment_quota for internal events when under quota."""
    engine = _make_engine()

    with (
        patch.object(engine, "_is_over_quota", new_callable=AsyncMock, return_value=False),
        patch.object(engine, "_increment_quota", new_callable=AsyncMock) as mock_inc,
    ):
        event = _make_event(EventSeverity.NOTABLE, tenant_id="t1")
        await engine._handle_event(event)

    mock_inc.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_handle_event_skips_increment_when_over_quota():
    """_handle_event should NOT call _increment_quota when over quota (event blocked)."""
    engine = _make_engine()

    with (
        patch.object(engine, "_is_over_quota", new_callable=AsyncMock, return_value=True),
        patch.object(engine, "_increment_quota", new_callable=AsyncMock) as mock_inc,
    ):
        event = _make_event(EventSeverity.NOTABLE, tenant_id="t1")
        await engine._handle_event(event)

    mock_inc.assert_not_called()


@pytest.mark.asyncio
async def test_increment_quota_calls_repo():
    """_increment_quota should call repo.increment_event_quota in SaaS mode."""
    engine = _make_engine()
    event = _make_event(tenant_id="t1")

    mock_repo = MagicMock()
    mock_sub = MagicMock()
    mock_sub.current_period_start = datetime(2026, 3, 1)

    with (
        patch("argus_agent.config.get_settings") as mock_settings,
        patch(
            "argus_agent.billing.usage_guard._get_tenant_and_subscription",
            new_callable=AsyncMock,
            return_value=(None, mock_sub),
        ),
        patch(
            "argus_agent.storage.repositories.get_metrics_repository",
            return_value=mock_repo,
        ),
    ):
        mock_settings.return_value.deployment.mode = "saas"
        await engine._increment_quota(event)

    mock_repo.increment_event_quota.assert_called_once()
    call_args = mock_repo.increment_event_quota.call_args
    assert call_args[0][0] == "t1"
    assert call_args[0][2] == 1


@pytest.mark.asyncio
async def test_increment_quota_skips_self_hosted():
    """_increment_quota should be a no-op in self-hosted mode."""
    engine = _make_engine()
    event = _make_event(tenant_id="t1")

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "self_hosted"
        # Should not raise or call anything
        await engine._increment_quota(event)


@pytest.mark.asyncio
async def test_increment_quota_skips_default_tenant():
    """_increment_quota should skip events with tenant_id 'default'."""
    engine = _make_engine()
    event = _make_event(tenant_id="default")

    mock_repo = MagicMock()

    with (
        patch("argus_agent.config.get_settings") as mock_settings,
        patch(
            "argus_agent.storage.repositories.get_metrics_repository",
            return_value=mock_repo,
        ),
    ):
        mock_settings.return_value.deployment.mode = "saas"
        await engine._increment_quota(event)

    mock_repo.increment_event_quota.assert_not_called()


@pytest.mark.asyncio
async def test_self_hosted_unaffected():
    """Self-hosted mode should never suppress alerts via quota."""
    engine = _make_engine()
    event = _make_event()

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "self_hosted"
        result = await engine._is_over_quota(event)

    assert result is False


@pytest.mark.asyncio
async def test_quota_check_cached():
    """Quota result should be cached per-tenant for 60s."""
    engine = _make_engine()
    event = _make_event(tenant_id="t1")

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "saas"

        with patch(
            "argus_agent.billing.usage_guard.check_event_ingest_limit",
            new_callable=AsyncMock,
        ) as mock_check:
            from fastapi import HTTPException

            mock_check.side_effect = HTTPException(status_code=429, detail="over limit")

            with patch("argus_agent.tenancy.context.get_tenant_id", return_value="t1"):
                result1 = await engine._is_over_quota(event)
                assert result1 is True
                assert mock_check.call_count == 1

                # Second call should use cache
                result2 = await engine._is_over_quota(event)
                assert result2 is True
                assert mock_check.call_count == 1  # not called again


@pytest.mark.asyncio
async def test_quota_cache_expires():
    """Cache should expire after TTL."""
    engine = _make_engine()
    event = _make_event(tenant_id="t1")
    # Manually set an expired cache
    engine._quota_cache["t1"] = (True, datetime(2000, 1, 1))

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "saas"

        with patch(
            "argus_agent.billing.usage_guard.check_event_ingest_limit",
            new_callable=AsyncMock,
        ):
            with patch("argus_agent.tenancy.context.get_tenant_id", return_value="t1"):
                result = await engine._is_over_quota(event)

    # check_event_ingest_limit didn't raise → not over quota
    assert result is False


@pytest.mark.asyncio
async def test_default_tenant_skips_quota():
    """Events with tenant_id 'default' should skip quota checks entirely."""
    engine = _make_engine()
    event = _make_event(tenant_id="default")

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "saas"

        with patch("argus_agent.tenancy.context.get_tenant_id", return_value="default"):
            result = await engine._is_over_quota(event)

    assert result is False


@pytest.mark.asyncio
async def test_per_tenant_cache_isolation():
    """Quota cache for tenant A must not affect tenant B."""
    engine = _make_engine()
    event_a = _make_event(tenant_id="tenant-a")
    event_b = _make_event(tenant_id="tenant-b")

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "saas"

        with patch(
            "argus_agent.billing.usage_guard.check_event_ingest_limit",
            new_callable=AsyncMock,
        ) as mock_check:
            from fastapi import HTTPException

            # Tenant A is over quota, tenant B is not
            async def _check(tid: str) -> None:
                if tid == "tenant-a":
                    raise HTTPException(status_code=429, detail="over limit")

            mock_check.side_effect = _check

            with patch("argus_agent.tenancy.context.get_tenant_id", return_value="tenant-a"):
                result_a = await engine._is_over_quota(event_a)
                assert result_a is True

            with patch("argus_agent.tenancy.context.get_tenant_id", return_value="tenant-b"):
                result_b = await engine._is_over_quota(event_b)
                assert result_b is False

            # Verify both were checked independently
            assert mock_check.call_count == 2


@pytest.mark.asyncio
async def test_tenant_id_from_event_data():
    """tenant_id should be read from event.data, not just contextvars."""
    engine = _make_engine()
    # Event has tenant_id in data, but contextvar returns something different
    event = _make_event(tenant_id="real-tenant")

    with patch("argus_agent.config.get_settings") as mock_settings:
        mock_settings.return_value.deployment.mode = "saas"

        with patch(
            "argus_agent.billing.usage_guard.check_event_ingest_limit",
            new_callable=AsyncMock,
        ) as mock_check:
            with patch("argus_agent.tenancy.context.get_tenant_id", return_value="wrong-tenant"):
                await engine._is_over_quota(event)

            # Should have been called with the tenant from event.data, not contextvar
            mock_check.assert_called_once_with("real-tenant")
