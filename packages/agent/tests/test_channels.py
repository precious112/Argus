"""Tests for notification channels."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.alerting.channels import (
    EmailChannel,
    SlackChannel,
    WebhookChannel,
    WebSocketChannel,
)
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


# ---- SlackChannel ----


@pytest.mark.asyncio
async def test_slack_channel_sends():
    channel = SlackChannel(bot_token="xoxb-test", channel_id="C123")

    mock_client = AsyncMock()
    mock_client.chat_postMessage = AsyncMock()

    import slack_sdk.web.async_client  # ensure module is loaded before patching

    with patch.object(
        slack_sdk.web.async_client, "AsyncWebClient",
        return_value=mock_client,
    ):
        result = await channel.send(_make_alert(), _make_event())

    assert result is True
    mock_client.chat_postMessage.assert_called_once()
    call_kwargs = mock_client.chat_postMessage.call_args[1]
    assert call_kwargs["channel"] == "C123"
    assert "blocks" in call_kwargs
    assert "attachments" in call_kwargs


@pytest.mark.asyncio
async def test_slack_channel_empty_token_noop():
    channel = SlackChannel(bot_token="", channel_id="C123")
    result = await channel.send(_make_alert(), _make_event())
    assert result is True


@pytest.mark.asyncio
async def test_slack_channel_empty_channel_noop():
    channel = SlackChannel(bot_token="xoxb-test", channel_id="")
    result = await channel.send(_make_alert(), _make_event())
    assert result is True


@pytest.mark.asyncio
async def test_slack_channel_handles_error():
    channel = SlackChannel(bot_token="xoxb-test", channel_id="C123")

    mock_client = AsyncMock()
    mock_client.chat_postMessage.side_effect = Exception("Slack API error")

    import slack_sdk.web.async_client  # ensure module is loaded before patching

    with patch.object(
        slack_sdk.web.async_client, "AsyncWebClient",
        return_value=mock_client,
    ):
        result = await channel.send(_make_alert(), _make_event())

    assert result is False


@pytest.mark.asyncio
async def test_slack_test_connection():
    channel = SlackChannel(bot_token="xoxb-test", channel_id="C123")

    mock_client = AsyncMock()
    mock_client.auth_test = AsyncMock(return_value={"team": "T", "user": "U"})
    mock_client.chat_postMessage = AsyncMock()

    import slack_sdk.web.async_client  # ensure module is loaded before patching

    with patch.object(
        slack_sdk.web.async_client, "AsyncWebClient",
        return_value=mock_client,
    ):
        result = await channel.test_connection()

    assert result["ok"] is True
    assert result["team"] == "T"
    mock_client.chat_postMessage.assert_called_once()


@pytest.mark.asyncio
async def test_slack_list_channels():
    channel = SlackChannel(bot_token="xoxb-test", channel_id="")

    mock_client = AsyncMock()
    mock_client.conversations_list = AsyncMock(return_value={
        "channels": [
            {"id": "C1", "name": "general"},
            {"id": "C2", "name": "alerts"},
        ],
        "response_metadata": {"next_cursor": ""},
    })

    import slack_sdk.web.async_client  # ensure module is loaded before patching

    with patch.object(
        slack_sdk.web.async_client, "AsyncWebClient",
        return_value=mock_client,
    ):
        result = await channel.list_channels()

    assert len(result) == 2
    assert result[0]["name"] == "general"


# ---- EmailChannel (HTML) ----


@pytest.mark.asyncio
async def test_email_channel_sends_html():
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

    # Verify multipart: plain text + html
    parts = list(msg.iter_parts())
    assert len(parts) == 2
    content_types = [p.get_content_type() for p in parts]
    assert "text/plain" in content_types
    assert "text/html" in content_types


@pytest.mark.asyncio
async def test_email_channel_with_smtp_auth():
    import sys
    import types

    channel = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        from_addr="argus@example.com",
        to_addrs=["admin@example.com"],
        smtp_user="user",
        smtp_password="pass",
        use_tls=True,
    )

    mock_send = AsyncMock()
    fake_module = types.ModuleType("aiosmtplib")
    fake_module.send = mock_send
    with patch.dict(sys.modules, {"aiosmtplib": fake_module}):
        result = await channel.send(_make_alert(), _make_event())

    assert result is True
    call_kwargs = mock_send.call_args[1]
    assert call_kwargs["username"] == "user"
    assert call_kwargs["password"] == "pass"
    assert call_kwargs["use_tls"] is True


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


@pytest.mark.asyncio
async def test_email_test_connection():
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
        result = await channel.test_connection()

    assert result["ok"] is True
    assert result["to"] == ["admin@example.com"]
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_email_html_contains_severity_color():
    html = EmailChannel._render_html(
        rule_name="CPU Critical",
        severity="URGENT",
        source="system_metrics",
        event_type="cpu_high",
        timestamp="2025-01-01T12:00:00",
        message="CPU at 99%",
        alert_id="alert-xyz",
    )
    assert "#e74c3c" in html  # red for URGENT
    assert "CPU Critical" in html
    assert "CPU at 99%" in html
    assert "alert-xyz" in html
