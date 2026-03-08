"""Tests for billing usage guards."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from argus_agent.billing.usage_guard import (
    _billing_period_start,
    check_api_key_limit,
    check_event_ingest_limit,
    check_team_member_limit,
)

_P = "argus_agent.billing.usage_guard"


def _mock_request(tenant_id: str = "t1", role: str = "admin") -> MagicMock:
    req = MagicMock()
    req.state.user = {"tenant_id": tenant_id, "role": role, "sub": "u1"}
    return req


def _mock_session_with_count(count: int):
    """Return a patched get_session whose execute returns *count*."""
    mock_session = MagicMock()
    session_cm = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar.return_value = count
    session_cm.execute = AsyncMock(return_value=scalar_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=session_cm)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_session


def _mock_tenant(plan: str = "teams", credit_balance: int = 0):
    """Create a mock Tenant object."""
    tenant = MagicMock()
    tenant.plan = plan
    tenant.payg_credit_balance_cents = credit_balance
    tenant.name = "Test Org"
    return tenant


def _mock_subscription(
    period_start: datetime | None = None,
    billing_interval: str = "month",
):
    """Create a mock Subscription object."""
    sub = MagicMock()
    sub.current_period_start = period_start
    sub.current_period_end = None
    sub.status = "active"
    sub.billing_interval = billing_interval
    return sub


@pytest.mark.asyncio
async def test_team_member_limit_noop_self_hosted():
    """Guard is a no-op when not in SaaS mode."""
    with patch(f"{_P}._is_saas", return_value=False):
        await check_team_member_limit(_mock_request())


@pytest.mark.asyncio
async def test_api_key_limit_noop_self_hosted():
    """Guard is a no-op when not in SaaS mode."""
    with patch(f"{_P}._is_saas", return_value=False):
        await check_api_key_limit(_mock_request())


@pytest.mark.asyncio
async def test_team_member_limit_free_at_limit():
    """Free plan: 1 member max -> should raise 403 when at 1."""
    mock_ses = _mock_session_with_count(1)
    with (
        patch(f"{_P}._is_saas", return_value=True),
        patch(f"{_P}._get_tenant_plan", new_callable=AsyncMock, return_value="free"),
        patch(f"{_P}.get_session", mock_ses),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await check_team_member_limit(_mock_request())
        assert exc_info.value.status_code == 403
        assert "limit reached" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_team_member_limit_teams_under_limit():
    """Teams plan: 10 members max -> should pass when at 3."""
    mock_ses = _mock_session_with_count(3)
    with (
        patch(f"{_P}._is_saas", return_value=True),
        patch(f"{_P}._get_tenant_plan", new_callable=AsyncMock, return_value="teams"),
        patch(f"{_P}.get_session", mock_ses),
    ):
        await check_team_member_limit(_mock_request())


@pytest.mark.asyncio
async def test_team_member_limit_teams_at_limit():
    """Teams plan: 10 members max -> should raise 403 when at 10."""
    mock_ses = _mock_session_with_count(10)
    with (
        patch(f"{_P}._is_saas", return_value=True),
        patch(f"{_P}._get_tenant_plan", new_callable=AsyncMock, return_value="teams"),
        patch(f"{_P}.get_session", mock_ses),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await check_team_member_limit(_mock_request())
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_team_member_limit_business_at_30():
    """Business plan: 30 members max -> should raise 403 when at 30."""
    mock_ses = _mock_session_with_count(30)
    with (
        patch(f"{_P}._is_saas", return_value=True),
        patch(f"{_P}._get_tenant_plan", new_callable=AsyncMock, return_value="business"),
        patch(f"{_P}.get_session", mock_ses),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await check_team_member_limit(_mock_request())
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_team_member_limit_business_under_limit():
    """Business plan: 30 members max -> should pass when at 15."""
    mock_ses = _mock_session_with_count(15)
    with (
        patch(f"{_P}._is_saas", return_value=True),
        patch(f"{_P}._get_tenant_plan", new_callable=AsyncMock, return_value="business"),
        patch(f"{_P}.get_session", mock_ses),
    ):
        await check_team_member_limit(_mock_request())


@pytest.mark.asyncio
async def test_api_key_limit_free_at_limit():
    """Free plan: 1 key max -> should raise 403 when at 1."""
    mock_ses = _mock_session_with_count(1)
    with (
        patch(f"{_P}._is_saas", return_value=True),
        patch(f"{_P}._get_tenant_plan", new_callable=AsyncMock, return_value="free"),
        patch(f"{_P}.get_session", mock_ses),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await check_api_key_limit(_mock_request())
        assert exc_info.value.status_code == 403
        assert "limit reached" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_api_key_limit_free_under_limit():
    """Free plan: 1 key max -> should pass when at 0."""
    mock_ses = _mock_session_with_count(0)
    with (
        patch(f"{_P}._is_saas", return_value=True),
        patch(f"{_P}._get_tenant_plan", new_callable=AsyncMock, return_value="free"),
        patch(f"{_P}.get_session", mock_ses),
    ):
        await check_api_key_limit(_mock_request())


# --- Event ingest limit + credit tests ---

_REPO_P = "argus_agent.storage.repositories.get_metrics_repository"
_SUB_P = f"{_P}._get_tenant_and_subscription"


@contextmanager
def _ingest_ctx(tenant, sub, mock_repo):
    """Common patches for event ingest tests."""
    with (
        patch(f"{_P}._is_saas", return_value=True),
        patch(
            _SUB_P,
            new_callable=AsyncMock,
            return_value=(tenant, sub),
        ),
        patch(_REPO_P, return_value=mock_repo),
    ):
        yield


@pytest.mark.asyncio
async def test_event_ingest_noop_self_hosted():
    """Guard is a no-op when not in SaaS mode."""
    with patch(f"{_P}._is_saas", return_value=False):
        await check_event_ingest_limit("t1")


@pytest.mark.asyncio
async def test_event_ingest_under_quota_allows():
    """Events under plan quota should be allowed."""
    tenant = _mock_tenant(plan="teams")
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=50_000)

    with _ingest_ctx(tenant, None, mock_repo):
        await check_event_ingest_limit("t1")


@pytest.mark.asyncio
async def test_event_ingest_over_quota_no_credits_rejects():
    """Events over plan quota without credits should raise 429."""
    tenant = _mock_tenant(plan="teams", credit_balance=0)
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=110_000)

    with _ingest_ctx(tenant, None, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await check_event_ingest_limit("t1")
        assert exc_info.value.status_code == 429
        assert "credits" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_event_ingest_over_quota_with_credits_allows():
    """Events over plan quota with credits should be allowed (deduction succeeds)."""
    tenant = _mock_tenant(plan="teams", credit_balance=1000)
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=110_000)

    with _ingest_ctx(tenant, None, mock_repo):
        with patch(
            "argus_agent.billing.payg.deduct_credits",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await check_event_ingest_limit("t1")


@pytest.mark.asyncio
async def test_event_ingest_credits_insufficient_rejects():
    """Events rejected when credit deduction fails (insufficient balance)."""
    tenant = _mock_tenant(plan="teams", credit_balance=1)
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=110_000)

    with _ingest_ctx(tenant, None, mock_repo):
        with patch(
            "argus_agent.billing.payg.deduct_credits",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await check_event_ingest_limit("t1")
            assert exc_info.value.status_code == 429
            assert "Insufficient credits" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_event_ingest_uses_subscription_period():
    """Events counted from subscription period start."""
    tenant = _mock_tenant(plan="teams")
    sub = _mock_subscription(period_start=datetime(2026, 2, 15))
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=50_000)

    with _ingest_ctx(tenant, sub, mock_repo):
        await check_event_ingest_limit("t1")
        mock_repo.get_event_quota_count.assert_called_once_with(
            "t1", datetime(2026, 2, 15),
        )


@pytest.mark.asyncio
async def test_event_ingest_free_plan_uses_calendar_month():
    """Free plan events counted from calendar month start."""
    tenant = _mock_tenant(plan="free")
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=100)

    with _ingest_ctx(tenant, None, mock_repo):
        await check_event_ingest_limit("t1")
        call_args = mock_repo.get_event_quota_count.call_args[0]
        assert call_args[1].day == 1


# --- _billing_period_start yearly sub-period tests ---


def test_billing_period_no_subscription():
    """No subscription returns first of current month."""
    result = _billing_period_start(None)
    assert result.day == 1


def test_billing_period_monthly_sub():
    """Monthly subscription returns period_start directly."""
    sub = _mock_subscription(
        period_start=datetime(2026, 2, 15),
        billing_interval="month",
    )
    result = _billing_period_start(sub)
    assert result == datetime(2026, 2, 15)


def test_billing_period_yearly_sub_same_month():
    """Yearly sub started Jan 15 — March query returns Mar 15 if past anchor."""
    sub = _mock_subscription(
        period_start=datetime(2026, 1, 15),
        billing_interval="year",
    )
    # Mock now to March 20
    with patch(f"{_P}.datetime") as mock_dt:
        now = datetime(2026, 3, 20, 12, 0, 0)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        result = _billing_period_start(sub)
    assert result == datetime(2026, 3, 15, 0, 0, 0)


def test_billing_period_yearly_sub_before_anchor():
    """Yearly sub started Jan 31 — in Feb (before anchor), should return Jan 28/31."""
    sub = _mock_subscription(
        period_start=datetime(2026, 1, 31),
        billing_interval="year",
    )
    # Mock now to Feb 10 (before Feb 28 anchor)
    with patch(f"{_P}.datetime") as mock_dt:
        now = datetime(2026, 2, 10, 12, 0, 0)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        result = _billing_period_start(sub)
    # Jan 31 anchor clamped to Jan 31 (previous month)
    assert result == datetime(2026, 1, 31, 0, 0, 0)


def test_billing_period_yearly_sub_day_clamping():
    """Yearly sub started Jan 31 — Feb should clamp to Feb 28."""
    sub = _mock_subscription(
        period_start=datetime(2026, 1, 31),
        billing_interval="year",
    )
    # Mock now to March 1 (past Feb 28 anchor for previous sub-period)
    with patch(f"{_P}.datetime") as mock_dt:
        now = datetime(2026, 3, 1, 12, 0, 0)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        result = _billing_period_start(sub)
    # Feb 28 (clamped from 31)
    assert result == datetime(2026, 2, 28, 0, 0, 0)
