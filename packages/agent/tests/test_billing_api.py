"""Tests for billing API endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from argus_agent.billing.plans import PLAN_LIMITS


@pytest.fixture
def _mock_app():
    """Create a minimal test app with billing routes."""
    from fastapi import FastAPI

    from argus_agent.api.billing import router as billing_router

    app = FastAPI()
    app.include_router(billing_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_list_plans(_mock_app):
    """GET /billing/plans returns plan data without authentication."""
    transport = ASGITransport(app=_mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/billing/plans")
    assert res.status_code == 200
    data = res.json()
    assert "plans" in data
    assert "pricing" in data
    assert "payg" in data
    assert len(data["plans"]) == len(PLAN_LIMITS)

    plan_ids = {p["id"] for p in data["plans"]}
    assert "free" in plan_ids
    assert "teams" in plan_ids
    assert "business" in plan_ids

    # Verify free plan values
    free = next(p for p in data["plans"] if p["id"] == "free")
    assert free["monthly_event_limit"] == 5_000
    assert free["max_team_members"] == 1

    # Verify teams plan values
    teams = next(p for p in data["plans"] if p["id"] == "teams")
    assert teams["monthly_event_limit"] == 100_000
    assert teams["max_team_members"] == 10

    # Verify business plan values
    biz = next(p for p in data["plans"] if p["id"] == "business")
    assert biz["monthly_event_limit"] == 300_000
    assert biz["max_team_members"] == 30


@pytest.mark.asyncio
async def test_list_plans_has_pricing(_mock_app):
    """GET /billing/plans includes pricing for Teams and Business."""
    transport = ASGITransport(app=_mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/billing/plans")
    data = res.json()
    pricing = data["pricing"]
    assert "teams" in pricing
    assert "business" in pricing
    assert pricing["teams"]["monthly"] == 25
    assert pricing["teams"]["annual"] == 240
    assert pricing["business"]["monthly"] == 60
    assert pricing["business"]["annual"] == 576


@pytest.mark.asyncio
async def test_list_plans_has_credits_info(_mock_app):
    """GET /billing/plans includes prepaid credits info."""
    transport = ASGITransport(app=_mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/billing/plans")
    data = res.json()
    payg = data["payg"]
    assert payg["rate_per_1k_dollars"] == 0.30
    assert payg["model"] == "prepaid_credits"
    assert "teams" in payg["available_on"]
    assert "business" in payg["available_on"]


@pytest.mark.asyncio
async def test_billing_status_requires_auth(_mock_app):
    """GET /billing/status requires authentication."""
    transport = ASGITransport(app=_mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/billing/status")
    # require_role() returns 401 when no auth cookie is present
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_checkout_requires_auth(_mock_app):
    """POST /billing/checkout requires authentication."""
    transport = ASGITransport(app=_mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/billing/checkout")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_credits_get_requires_auth(_mock_app):
    """GET /billing/credits requires authentication."""
    transport = ASGITransport(app=_mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/billing/credits")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_credits_checkout_requires_auth(_mock_app):
    """POST /billing/credits/checkout requires authentication."""
    transport = ASGITransport(app=_mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/billing/credits/checkout",
            json={"amount_dollars": 10},
        )
    assert res.status_code == 401
