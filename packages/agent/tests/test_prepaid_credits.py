"""Tests for prepaid credit service (payg.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.billing.payg import add_credits, deduct_credits, get_credit_status

_P = "argus_agent.billing.payg"


def _mock_tenant(balance: int = 0):
    """Create a mock Tenant with credit balance."""
    t = MagicMock()
    t.payg_credit_balance_cents = balance
    return t


def _mock_session_for_credits(tenant, *, returning_balance: int | None = None):
    """Build a mock get_session that supports get() and execute()."""
    session_cm = AsyncMock()
    session_cm.get = AsyncMock(return_value=tenant)

    # Mock for text() RETURNING queries
    if returning_balance is not None:
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (returning_balance,)
        session_cm.execute = AsyncMock(return_value=mock_result)
    else:
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session_cm.execute = AsyncMock(return_value=mock_result)

    session_cm.add = MagicMock()
    session_cm.commit = AsyncMock()

    # Mock for select() queries (used by get_credit_status)
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    mock_select_result = MagicMock()
    mock_select_result.scalars.return_value = scalars_result

    # If execute is called with a select (not text), return the select result
    original_execute = session_cm.execute

    async def smart_execute(query, *args, **kwargs):
        if args or kwargs:  # text() queries pass params
            return await original_execute(query, *args, **kwargs)
        return mock_select_result

    session_cm.execute = AsyncMock(side_effect=smart_execute)

    mock_session = MagicMock()
    mock_session.return_value.__aenter__ = AsyncMock(return_value=session_cm)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_session


@pytest.mark.asyncio
async def test_get_credit_status_no_tenant():
    """Returns zero balance for nonexistent tenant."""
    session = _mock_session_for_credits(None)
    with patch(f"{_P}.get_session", session):
        result = await get_credit_status("t-missing")
    assert result["balance_cents"] == 0
    assert result["balance_dollars"] == 0.0
    assert result["recent_transactions"] == []


@pytest.mark.asyncio
async def test_get_credit_status_with_balance():
    """Returns correct balance for tenant with credits."""
    tenant = _mock_tenant(balance=1500)
    session = _mock_session_for_credits(tenant)
    with patch(f"{_P}.get_session", session):
        result = await get_credit_status("t1")
    assert result["balance_cents"] == 1500
    assert result["balance_dollars"] == 15.0


@pytest.mark.asyncio
async def test_add_credits_success():
    """add_credits returns new balance and creates transaction."""
    tenant = _mock_tenant(balance=0)
    session = _mock_session_for_credits(tenant, returning_balance=1000)
    with patch(f"{_P}._get_raw_session", session):
        new_balance = await add_credits("t1", 1000, polar_order_id="ord_123")
    assert new_balance == 1000


@pytest.mark.asyncio
async def test_add_credits_nonexistent_tenant():
    """add_credits returns 0 for missing tenant."""
    session = _mock_session_for_credits(None, returning_balance=None)
    with patch(f"{_P}._get_raw_session", session):
        new_balance = await add_credits("t-missing", 500)
    assert new_balance == 0


@pytest.mark.asyncio
async def test_deduct_credits_success():
    """deduct_credits returns True when balance sufficient."""
    tenant = _mock_tenant(balance=1000)
    session = _mock_session_for_credits(tenant, returning_balance=990)
    with patch(f"{_P}._get_raw_session", session):
        result = await deduct_credits("t1", 10, 100)
    assert result is True


@pytest.mark.asyncio
async def test_deduct_credits_insufficient():
    """deduct_credits returns False when balance insufficient."""
    tenant = _mock_tenant(balance=5)
    # fetchone returns None when WHERE clause fails (insufficient balance)
    session = _mock_session_for_credits(tenant, returning_balance=None)
    with patch(f"{_P}._get_raw_session", session):
        result = await deduct_credits("t1", 10, 100)
    assert result is False
