"""Tests for notification channels."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.alerting.channels import EmailChannel, WebhookChannel, WebSocketChannel
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType


def _make_alert(severity=EventSeverity.URGENT, rule_name="Test Rule"):
    """Create a mock alert object."""
    alert = MagicMock()
    alert.id = "alert-123"
    alert.severity = severity
    alert.rule_name = rule_name
    alert.timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    return alert


def _make_event(msg="Test alert message"):
    return Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=EventSeverity.URGENT,
        message=msg,
    )


# ---- WebSocketChannel ----


@pytest.mark.asyncio
async def test_websocket_channel_broadcasts():
    manager = AsyncMock()
    channel = WebSocketChannel(manager)

    result = await channel.send(_make_alert(), _make_event())
    assert result is True
    manager.broadcast.assert_called_once()

    # Verify the broadcast message
    call_args = manager.broadcast.call_args[0][0]
    assert call_args.type == "alert"


@pytest.mark.asyncio
async def test_websocket_channel_handles_error():
    manager = AsyncMock()
    manager.broadcast.side_effect = ConnectionError("disconnected")
    channel = WebSocketChannel(manager)

    result = await channel.send(_make_alert(), _make_event())
    assert result is False


# ---- WebhookChannel ----


@pytest.mark.asyncio
async def test_webhook_channel_generic():
    channel = WebhookChannel(["https://example.com/hook"])

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await channel.send(_make_alert(), _make_event())

    assert result is True
    mock_client.post.assert_called_once()
    payload = mock_client.post.call_args[1]["json"]
    assert "title" in payload
    assert "severity" in payload


@pytest.mark.asyncio
async def test_webhook_slack_format():
    channel = WebhookChannel(["https://hooks.slack.com/services/T00/B00/xxx"])

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await channel.send(_make_alert(), _make_event())

    payload = mock_client.post.call_args[1]["json"]
    assert "text" in payload
    assert "blocks" in payload


@pytest.mark.asyncio
async def test_webhook_discord_format():
    channel = WebhookChannel(["https://discord.com/api/webhooks/123/abc"])

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await channel.send(_make_alert(), _make_event())

    payload = mock_client.post.call_args[1]["json"]
    assert "content" in payload


@pytest.mark.asyncio
async def test_webhook_empty_urls():
    channel = WebhookChannel([])
    result = await channel.send(_make_alert(), _make_event())
    assert result is True


@pytest.mark.asyncio
async def test_webhook_handles_http_error():
    channel = WebhookChannel(["https://example.com/hook"])

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = ConnectionError("network error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await channel.send(_make_alert(), _make_event())

    assert result is False


# ---- EmailChannel ----


@pytest.mark.asyncio
async def test_email_channel_sends():
    import sys
    import types

    channel = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        from_addr="argus@example.com",
        to_addrs=["admin@example.com"],
    )

    mock_send = AsyncMock()
    fake_module = types.ModuleType("aiosmtplib")
    fake_module.send = mock_send
    with patch.dict(sys.modules, {"aiosmtplib": fake_module}):
        result = await channel.send(_make_alert(), _make_event())

    assert result is True
    mock_send.assert_called_once()
    msg = mock_send.call_args[0][0]
    assert "Test Rule" in msg["Subject"]


@pytest.mark.asyncio
async def test_email_channel_empty_recipients():
    channel = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        from_addr="argus@example.com",
        to_addrs=[],
    )
    result = await channel.send(_make_alert(), _make_event())
    assert result is True  # No-op, success
