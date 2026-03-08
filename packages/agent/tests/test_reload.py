"""Tests for notification channel runtime reload."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from argus_agent.alerting.channels import (
    EmailChannel,
    SlackChannel,
    WebhookChannel,
    WebSocketChannel,
)
from argus_agent.alerting.reload import reload_channels
from argus_agent.alerting.settings import NotificationSettingsService
from argus_agent.storage.models import Base


@pytest.fixture()
async def _init_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    import argus_agent.storage.database as db_mod
    import argus_agent.storage.repositories as repo_mod
    from argus_agent.storage.sqlite_operational import SQLiteOperationalRepository

    monkeypatch.setattr(db_mod, "_session_factory", factory)
    monkeypatch.setattr(repo_mod, "_operational_repo", SQLiteOperationalRepository())
    yield
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_reload_creates_channels_from_db():
    # Seed some configs
    svc = NotificationSettingsService()
    await svc.upsert("slack", True, {"bot_token": "xoxb-t", "channel_id": "C1"})
    await svc.upsert("email", True, {
        "smtp_host": "smtp.test.com",
        "smtp_port": 587,
        "from_addr": "a@b.com",
        "to_addrs": ["c@d.com"],
    })
    await svc.upsert("webhook", True, {"urls": ["https://example.com/hook"]})

    mock_engine = MagicMock()
    engine_channels: list = []
    mock_engine.set_channels = lambda ch: engine_channels.extend(ch)

    mock_formatter = MagicMock()
    formatter_channels: list = []
    mock_formatter.set_channels = lambda ch: formatter_channels.extend(ch)

    mock_manager = AsyncMock()

    with (
        patch("argus_agent.main._get_alert_engine", return_value=mock_engine),
        patch("argus_agent.main._get_alert_formatter", return_value=mock_formatter),
        patch("argus_agent.api.ws.manager", mock_manager),
    ):
        await reload_channels()

    # Engine gets only WebSocket
    assert len(engine_channels) == 1
    assert isinstance(engine_channels[0], WebSocketChannel)

    # Formatter gets external channels: Slack + Email + Webhook = 3
    assert len(formatter_channels) == 3
    types = {type(c) for c in formatter_channels}
    assert SlackChannel in types
    assert EmailChannel in types
    assert WebhookChannel in types


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_reload_skips_disabled_channels():
    svc = NotificationSettingsService()
    await svc.upsert("slack", False, {"bot_token": "xoxb-t", "channel_id": "C1"})
    await svc.upsert("email", True, {
        "smtp_host": "smtp.test.com",
        "smtp_port": 587,
        "from_addr": "a@b.com",
        "to_addrs": ["c@d.com"],
    })

    mock_engine = MagicMock()
    engine_channels: list = []
    mock_engine.set_channels = lambda ch: engine_channels.extend(ch)

    mock_formatter = MagicMock()
    formatter_channels: list = []
    mock_formatter.set_channels = lambda ch: formatter_channels.extend(ch)

    mock_manager = AsyncMock()

    with (
        patch("argus_agent.main._get_alert_engine", return_value=mock_engine),
        patch("argus_agent.main._get_alert_formatter", return_value=mock_formatter),
        patch("argus_agent.api.ws.manager", mock_manager),
    ):
        await reload_channels()

    # Engine: WebSocket only
    assert len(engine_channels) == 1
    assert isinstance(engine_channels[0], WebSocketChannel)

    # Formatter: Email only (Slack disabled)
    assert len(formatter_channels) == 1
    types = {type(c) for c in formatter_channels}
    assert EmailChannel in types
    assert SlackChannel not in types


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_reload_always_includes_websocket():
    mock_engine = MagicMock()
    engine_channels: list = []
    mock_engine.set_channels = lambda ch: engine_channels.extend(ch)

    mock_formatter = MagicMock()
    formatter_channels: list = []
    mock_formatter.set_channels = lambda ch: formatter_channels.extend(ch)

    mock_manager = AsyncMock()

    with (
        patch("argus_agent.main._get_alert_engine", return_value=mock_engine),
        patch("argus_agent.main._get_alert_formatter", return_value=mock_formatter),
        patch("argus_agent.api.ws.manager", mock_manager),
    ):
        await reload_channels()

    # Even with no DB configs, WebSocket is always present on engine
    assert len(engine_channels) == 1
    assert isinstance(engine_channels[0], WebSocketChannel)

    # No external channels
    assert len(formatter_channels) == 0


@pytest.mark.asyncio
async def test_reload_no_engine_is_noop():
    """reload_channels should not crash if AlertEngine isn't initialised."""
    with patch("argus_agent.main._get_alert_engine", return_value=None):
        await reload_channels()  # Should not raise
