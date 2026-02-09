"""Tests for REST API endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
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
    resp = await client.post("/api/v1/ingest", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1
