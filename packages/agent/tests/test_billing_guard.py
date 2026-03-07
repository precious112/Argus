"""Tests for billing usage guards."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from argus_agent.billing.usage_guard import (
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


def _mock_tenant(plan: str = "teams", payg_enabled: bool = False, payg_budget: int = 0):
    """Create a mock Tenant object."""
    tenant = MagicMock()
    tenant.plan = plan
    tenant.payg_enabled = payg_enabled
    tenant.payg_monthly_budget_cents = payg_budget
    tenant.name = "Test Org"
    return tenant


def _mock_subscription(period_start: datetime | None = None):
    """Create a mock Subscription object."""
    sub = MagicMock()
    sub.current_period_start = period_start
    sub.current_period_end = None
    sub.status = "active"
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


# --- Event ingest limit + PAYG tests ---

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
async def test_event_ingest_over_quota_no_payg_rejects():
    """Events over plan quota without PAYG should raise 429."""
    tenant = _mock_tenant(plan="teams", payg_enabled=False)
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=110_000)

    with _ingest_ctx(tenant, None, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await check_event_ingest_limit("t1")
        assert exc_info.value.status_code == 429
        assert "Pay-As-You-Go" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_event_ingest_over_quota_payg_allows():
    """Events over plan quota with PAYG budget should be allowed."""
    tenant = _mock_tenant(
        plan="teams", payg_enabled=True, payg_budget=1000,
    )
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=110_000)

    with _ingest_ctx(tenant, None, mock_repo):
        await check_event_ingest_limit("t1")


@pytest.mark.asyncio
async def test_event_ingest_payg_budget_exhausted_rejects():
    """Events rejected when PAYG budget is exhausted."""
    # $1=100c. 10K overage * 0.03c/event = 300c > 100c budget
    tenant = _mock_tenant(
        plan="teams", payg_enabled=True, payg_budget=100,
    )
    mock_repo = MagicMock()
    mock_repo.get_event_quota_count = MagicMock(return_value=110_000)

    with _ingest_ctx(tenant, None, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await check_event_ingest_limit("t1")
        assert exc_info.value.status_code == 429
        assert "PAYG budget exhausted" in str(exc_info.value.detail)


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
