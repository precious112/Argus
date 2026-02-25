"""Tests for REST API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from argus_agent.auth.jwt import create_access_token
from argus_agent.config import reset_settings
from argus_agent.main import create_app


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    token = create_access_token("test-user-id", "test")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"argus_token": token},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_system_status(client):
    resp = await client.get("/api/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "collectors" in data
    assert "agent" in data


@pytest.mark.asyncio
async def test_ingest_endpoint(client):
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock()
    payload = {
        "events": [
            {
                "type": "log",
                "service": "test-app",
                "data": {"message": "test log line"},
            }
        ],
        "sdk": "argus-python/0.1.0",
        "service": "test-app",
    }
    with patch("argus_agent.storage.timeseries.get_connection", return_value=mock_conn):
        resp = await client.post("/api/v1/ingest", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1


# --- Phase 3 API Tests ---


@pytest.mark.asyncio
async def test_alerts_endpoint_empty(client):
    resp = await client.get("/api/v1/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data
    assert "count" in data


@pytest.mark.asyncio
async def test_budget_endpoint(client):
    resp = await client.get("/api/v1/budget")
    assert resp.status_code == 200
    data = resp.json()
    # Budget may not be initialized without lifespan, but endpoint should not crash
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_investigations_endpoint(client):
    resp = await client.get("/api/v1/investigations")
    assert resp.status_code == 200
    data = resp.json()
    assert "investigations" in data


@pytest.mark.asyncio
async def test_security_endpoint(client):
    resp = await client.get("/api/v1/security")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_resolve_alert_not_found(client):
    resp = await client.post("/api/v1/alerts/nonexistent-id/resolve")
    # Either 404 (alert engine running) or 503 (not initialized)
    assert resp.status_code in (404, 503)


@pytest.mark.asyncio
async def test_alerts_with_severity_filter(client):
    resp = await client.get("/api/v1/alerts?severity=URGENT")
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data


@pytest.mark.asyncio
async def test_alerts_with_resolved_filter(client):
    resp = await client.get("/api/v1/alerts?resolved=false")
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data


@pytest.mark.asyncio
async def test_health_includes_version(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] is not None
