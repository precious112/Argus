"""Tests for billing usage guards."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from argus_agent.billing.usage_guard import (
    check_api_key_limit,
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
