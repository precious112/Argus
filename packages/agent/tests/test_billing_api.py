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
    assert "usage_tiers" in data
    assert len(data["plans"]) == len(PLAN_LIMITS)

    plan_ids = {p["id"] for p in data["plans"]}
    assert "free" in plan_ids
    assert "teams" in plan_ids

    # Verify free plan values
    free = next(p for p in data["plans"] if p["id"] == "free")
    assert free["monthly_event_limit"] == 5_000
    assert free["max_team_members"] == 1

    # Verify teams plan values
    teams = next(p for p in data["plans"] if p["id"] == "teams")
    assert teams["monthly_event_limit"] == 100_000
    assert teams["max_team_members"] == 10


@pytest.mark.asyncio
async def test_list_plans_has_usage_tiers(_mock_app):
    """GET /billing/plans includes usage-based scaling tiers."""
    transport = ASGITransport(app=_mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/billing/plans")
    data = res.json()
    tiers = data["usage_tiers"]
    assert len(tiers) >= 3
    assert tiers[0]["up_to_events"] == 100_000
    assert tiers[0]["price_dollars"] == 25


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
