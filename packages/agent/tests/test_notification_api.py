"""Tests for notification REST API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from argus_agent.storage.models import Base


@pytest.fixture()
async def client(monkeypatch):
    """Create a test client with in-memory DB."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    import argus_agent.storage.database as db_mod

    monkeypatch.setattr(db_mod, "_session_factory", factory)

    # Import the app and create test client
    from fastapi import FastAPI

    from argus_agent.api.rest import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_notification_settings_empty(client):
    r = await client.get("/api/v1/notifications/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["channels"] == []


@pytest.mark.asyncio
async def test_upsert_notification_setting(client):
    # Mock reload_channels since there's no running AlertEngine
    with patch("argus_agent.alerting.reload.reload_channels", new_callable=AsyncMock):
        r = await client.put(
            "/api/v1/notifications/settings/slack",
            json={
                "enabled": True,
                "config": {"bot_token": "xoxb-test", "channel_id": "C123"},
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["channel_type"] == "slack"
    assert data["enabled"] is True
    # Token should be masked in response
    assert data["config"]["bot_token"] == "••••••••"


@pytest.mark.asyncio
async def test_upsert_invalid_channel_type(client):
    r = await client.put(
        "/api/v1/notifications/settings/invalid",
        json={"enabled": True, "config": {}},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_test_notification_not_configured(client):
    r = await client.post("/api/v1/notifications/test/slack")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_test_slack_notification(client):
    # First, create the config
    with patch("argus_agent.alerting.reload.reload_channels", new_callable=AsyncMock):
        await client.put(
            "/api/v1/notifications/settings/slack",
            json={
                "enabled": True,
                "config": {"bot_token": "xoxb-test", "channel_id": "C123"},
            },
        )

    # Test notification — mock SlackChannel.test_connection
    with patch(
        "argus_agent.alerting.channels.SlackChannel.test_connection",
        new_callable=AsyncMock,
        return_value={"ok": True, "team": "TestTeam", "bot": "argus-bot"},
    ):
        r = await client.post("/api/v1/notifications/test/slack")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_test_email_notification(client):
    with patch("argus_agent.alerting.reload.reload_channels", new_callable=AsyncMock):
        await client.put(
            "/api/v1/notifications/settings/email",
            json={
                "enabled": True,
                "config": {
                    "smtp_host": "smtp.test.com",
                    "smtp_port": 587,
                    "from_addr": "a@b.com",
                    "to_addrs": ["c@d.com"],
                },
            },
        )

    with patch(
        "argus_agent.alerting.channels.EmailChannel.test_connection",
        new_callable=AsyncMock,
        return_value={"ok": True, "to": ["c@d.com"]},
    ):
        r = await client.post("/api/v1/notifications/test/email")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_list_slack_channels_not_configured(client):
    r = await client.get("/api/v1/notifications/slack/channels")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_slack_channels(client):
    with patch("argus_agent.alerting.reload.reload_channels", new_callable=AsyncMock):
        await client.put(
            "/api/v1/notifications/settings/slack",
            json={
                "enabled": True,
                "config": {"bot_token": "xoxb-test", "channel_id": "C123"},
            },
        )

    with patch(
        "argus_agent.alerting.channels.SlackChannel.list_channels",
        new_callable=AsyncMock,
        return_value=[{"id": "C1", "name": "general"}, {"id": "C2", "name": "alerts"}],
    ):
        r = await client.get("/api/v1/notifications/slack/channels")
    assert r.status_code == 200
    data = r.json()
    assert len(data["channels"]) == 2
