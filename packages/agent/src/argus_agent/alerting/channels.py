"""Notification channels: WebSocket, webhook, email, Slack Bot."""

from __future__ import annotations

import logging
import ssl
from abc import ABC, abstractmethod
from typing import Any

from argus_agent.api.protocol import AlertMessage, ServerMessage, ServerMessageType

logger = logging.getLogger("argus.alerting.channels")

_SEVERITY_COLORS = {
    "URGENT": "#e74c3c",
    "NOTABLE": "#f39c12",
    "NORMAL": "#2ecc71",
}


class NotificationChannel(ABC):
    """Base class for alert notification channels."""

    @abstractmethod
    async def send(self, alert: Any, event: Any) -> bool:
        """Send a notification for the given alert/event. Returns True on success."""
        ...

    async def send_urgent(self, alert: Any, event: Any, friendly_message: str) -> bool:
        """Send an urgent alert with a human-friendly message. Default: fall back to send()."""
        return await self.send(alert, event)

    async def send_digest(self, digest: Any) -> bool:
        """Send a batched digest of NOTABLE alerts. Default: send each individually."""
        success = True
        for group in digest.groups:
            for item in group.items:
                if not await self.send(item.alert, item.event):
                    success = False
        return success

    async def send_investigation_report(self, title: str, summary: str) -> bool:
        """Send an AI investigation report. Default: no-op."""
        return True


class WebSocketChannel(NotificationChannel):
    """Broadcasts alerts to all connected WebSocket clients."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    async def send(self, alert: Any, event: Any) -> bool:
        try:
            msg = ServerMessage(
                type=ServerMessageType.ALERT,
                data=AlertMessage(
                    id=alert.id,
                    severity=str(alert.severity),
                    title=alert.rule_name,
                    summary=event.message or "",
                    source=str(event.source),
                    timestamp=alert.timestamp,
                ).model_dump(mode="json"),
            )
            await self._manager.broadcast(msg)
            return True
        except Exception:
            logger.exception("WebSocket alert broadcast failed")
            return False


class WebhookChannel(NotificationChannel):
    """Sends alerts via HTTP POST. Auto-detects Slack/Discord URL patterns."""

    def __init__(self, urls: list[str]) -> None:
        self._urls = urls

    async def send(self, alert: Any, event: Any) -> bool:
        if not self._urls:
            return True

        import httpx

        success = True
        for url in self._urls:
            payload = self._format_payload(url, alert, event)
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code >= 400:
                        logger.warning("Webhook returned %d for %s", resp.status_code, url)
                        success = False
            except Exception:
                logger.exception("Webhook POST failed for %s", url)
                success = False
        return success

    async def send_investigation_report(self, title: str, summary: str) -> bool:
        if not self._urls:
            return True

        import httpx

        success = True
        for url in self._urls:
            payload: dict[str, Any]
            if "hooks.slack.com" in url:
                payload = {"text": f"*\U0001f916 AI Investigation Report — {title}*\n{summary}"}
            elif "discord.com/api/webhooks" in url:
                payload = {"content": f"**AI Investigation Report — {title}**\n{summary}"}
            else:
                payload = {"type": "investigation_report", "title": title, "summary": summary}
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code >= 400:
                        logger.warning("Webhook investigation report returned %d", resp.status_code)
                        success = False
            except Exception:
                logger.exception("Webhook investigation report failed for %s", url)
                success = False
        return success

    @staticmethod
    def _format_payload(url: str, alert: Any, event: Any) -> dict[str, Any]:
        title = f"[{alert.severity}] {alert.rule_name}"
        body = event.message or "No details available"

        if "hooks.slack.com" in url:
            return {
                "text": f"*{title}*\n{body}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*{title}*\n{body}"},
                    }
                ],
            }
        if "discord.com/api/webhooks" in url:
            return {
                "content": f"**{title}**\n{body}",
            }
        # Generic webhook
        return {
            "title": title,
            "message": body,
            "severity": str(alert.severity),
            "source": str(event.source),
            "event_type": str(event.type),
            "timestamp": alert.timestamp.isoformat(),
        }


class SlackChannel(NotificationChannel):
    """Posts alerts to Slack via the Web API (Bot token)."""

    def __init__(self, bot_token: str, channel_id: str) -> None:
        self._bot_token = bot_token
        self._channel_id = channel_id
        self._ssl_context = ssl.create_default_context()

    async def send(self, alert: Any, event: Any) -> bool:
        if not self._bot_token or not self._channel_id:
            return True

        try:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=self._bot_token, ssl=self._ssl_context)
            severity = str(alert.severity)
            color = _SEVERITY_COLORS.get(severity, "#95a5a6")
            message = event.message or "No details available"

            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"Argus Alert: {alert.rule_name}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                        {"type": "mrkdwn", "text": f"*Source:*\n{event.source}"},
                        {"type": "mrkdwn", "text": f"*Type:*\n{event.type}"},
                        {"type": "mrkdwn", "text": f"*Time:*\n{alert.timestamp.isoformat()}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{message}```"},
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Alert ID: `{alert.id}`"},
                    ],
                },
            ]

            await client.chat_postMessage(
                channel=self._channel_id,
                text=f"[{severity}] {alert.rule_name}: {message}",
                blocks=blocks,
                attachments=[{"color": color, "blocks": []}],
            )
            return True
        except Exception:
            logger.exception("Slack notification failed")
            return False

    async def list_channels(self) -> list[dict[str, str]]:
        """List Slack channels the bot can see."""
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=self._bot_token, ssl=self._ssl_context)
        result = []
        cursor = None
        while True:
            resp = await client.conversations_list(
                types="public_channel,private_channel",
                limit=200,
                cursor=cursor,
            )
            for ch in resp["channels"]:
                result.append({"id": ch["id"], "name": ch["name"]})
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return result

    async def send_urgent(self, alert: Any, event: Any, friendly_message: str) -> bool:
        if not self._bot_token or not self._channel_id:
            return True
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=self._bot_token, ssl=self._ssl_context)
            severity = str(alert.severity)
            color = _SEVERITY_COLORS.get(severity, "#e74c3c")

            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"\U0001f534 {alert.rule_name}"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": friendly_message},
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "\u23f3 AI investigation in progress..."},
                    ],
                },
            ]

            await client.chat_postMessage(
                channel=self._channel_id,
                text=f"\U0001f534 {alert.rule_name}: {friendly_message}",
                blocks=blocks,
                attachments=[{"color": color, "blocks": []}],
            )
            return True
        except Exception:
            logger.exception("Slack urgent notification failed")
            return False

    async def send_digest(self, digest: Any) -> bool:
        if not self._bot_token or not self._channel_id:
            return True
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=self._bot_token, ssl=self._ssl_context)

            lines = [
                f"\U0001f4cb *Argus Summary* — {digest.total_count} alert(s) "
                f"in the last {digest.window_seconds}s\n"
            ]
            for group in digest.groups:
                prefix = f"\U0001f7e1 ({group.count}x) " if group.count > 1 else "\U0001f7e1 "
                lines.append(f"{prefix}{group.summary}")

            if digest.ai_summary:
                lines.append(f"\n\U0001f916 *AI Assessment:* {digest.ai_summary}")

            body = "\n".join(lines)

            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": body},
                },
            ]

            await client.chat_postMessage(
                channel=self._channel_id,
                text=f"Argus Summary — {digest.total_count} alert(s)",
                blocks=blocks,
                attachments=[{"color": _SEVERITY_COLORS["NOTABLE"], "blocks": []}],
            )
            return True
        except Exception:
            logger.exception("Slack digest notification failed")
            return False

    async def send_investigation_report(self, title: str, summary: str) -> bool:
        if not self._bot_token or not self._channel_id:
            return True
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=self._bot_token, ssl=self._ssl_context)

            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "\U0001f916 AI Investigation Report"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{title}*\n\n{summary}"},
                },
            ]

            await client.chat_postMessage(
                channel=self._channel_id,
                text=f"AI Investigation Report — {title}",
                blocks=blocks,
            )
            return True
        except Exception:
            logger.exception("Slack investigation report failed")
            return False

    async def test_connection(self) -> dict[str, Any]:
        """Test the Slack connection and send a test message."""
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=self._bot_token, ssl=self._ssl_context)
        auth = await client.auth_test()
        await client.chat_postMessage(
            channel=self._channel_id,
            text="Argus test notification — Slack channel connected successfully.",
        )
        return {"ok": True, "team": auth["team"], "bot": auth["user"]}


class EmailChannel(NotificationChannel):
    """Sends alert emails via SMTP as HTML + plain-text multipart."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_addr: str,
        to_addrs: list[str],
        smtp_user: str = "",
        smtp_password: str = "",
        use_tls: bool = True,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._from_addr = from_addr
        self._to_addrs = to_addrs
        self._smtp_user = smtp_user
        self._smtp_password = smtp_password
        self._use_tls = use_tls

    async def send(self, alert: Any, event: Any) -> bool:
        if not self._to_addrs:
            return True

        try:
            from email.message import EmailMessage

            import aiosmtplib

            severity = str(alert.severity)
            title = f"[Argus {severity}] {alert.rule_name}"
            message = event.message or "No details available"

            plain = (
                f"Alert: {alert.rule_name}\n"
                f"Severity: {severity}\n"
                f"Source: {event.source}\n"
                f"Type: {event.type}\n"
                f"Time: {alert.timestamp.isoformat()}\n\n"
                f"{message}\n\n"
                f"Alert ID: {alert.id}"
            )

            html = self._render_html(
                rule_name=alert.rule_name,
                severity=severity,
                source=str(event.source),
                event_type=str(event.type),
                timestamp=alert.timestamp.isoformat(),
                message=message,
                alert_id=alert.id,
            )

            msg = EmailMessage()
            msg["Subject"] = title
            msg["From"] = self._from_addr
            msg["To"] = ", ".join(self._to_addrs)
            msg.set_content(plain)
            msg.add_alternative(html, subtype="html")

            await aiosmtplib.send(msg, **self._smtp_kwargs())
            return True
        except Exception:
            logger.exception("Email notification failed")
            return False

    async def send_investigation_report(self, title: str, summary: str) -> bool:
        if not self._to_addrs:
            return True
        try:
            from email.message import EmailMessage

            import aiosmtplib

            subject = f"[Argus] AI Investigation Report — {title}"
            plain = f"AI Investigation Report — {title}\n\n{summary}"
            html = (
                "<html><body>"
                f"<h2>AI Investigation Report — {title}</h2>"
                f"<p style='white-space:pre-wrap;'>{summary}</p>"
                "</body></html>"
            )

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self._from_addr
            msg["To"] = ", ".join(self._to_addrs)
            msg.set_content(plain)
            msg.add_alternative(html, subtype="html")

            await aiosmtplib.send(msg, **self._smtp_kwargs())
            return True
        except Exception:
            logger.exception("Email investigation report failed")
            return False

    def _smtp_kwargs(self) -> dict[str, Any]:
        """Build kwargs for aiosmtplib.send with correct TLS mode."""
        kwargs: dict[str, Any] = {
            "hostname": self._smtp_host,
            "port": self._smtp_port,
        }
        if self._use_tls:
            # Port 465 uses implicit TLS; port 587 (and others) use STARTTLS
            if self._smtp_port == 465:
                kwargs["use_tls"] = True
            else:
                kwargs["start_tls"] = True
        if self._smtp_user:
            kwargs["username"] = self._smtp_user
            kwargs["password"] = self._smtp_password
        return kwargs

    async def test_connection(self) -> dict[str, Any]:
        """Send a test email."""
        from email.message import EmailMessage

        import aiosmtplib

        msg = EmailMessage()
        msg["Subject"] = "[Argus] Test Notification"
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._to_addrs)
        msg.set_content("This is a test notification from Argus.")
        msg.add_alternative(
            "<html><body><h2>Argus Test</h2>"
            "<p>Email notifications are configured correctly.</p></body></html>",
            subtype="html",
        )

        await aiosmtplib.send(msg, **self._smtp_kwargs())
        return {"ok": True, "to": self._to_addrs}

    @staticmethod
    def _render_html(
        *,
        rule_name: str,
        severity: str,
        source: str,
        event_type: str,
        timestamp: str,
        message: str,
        alert_id: str,
    ) -> str:
        color = _SEVERITY_COLORS.get(severity, "#95a5a6")
        body_style = (
            "margin:0;padding:0;"
            "font-family:Arial,Helvetica,sans-serif;"
            "background:#f4f4f7;"
        )
        outer = (
            "background:#ffffff;"
            "border-radius:8px;overflow:hidden;"
        )
        msg_style = (
            f"margin-top:16px;padding:12px;background:#f8f9fa;"
            f"border-left:4px solid {color};"
            f"font-size:14px;white-space:pre-wrap;"
        )
        return (
            f'<html><body style="{body_style}">'
            f'<table width="100%" cellpadding="0" '
            f'cellspacing="0" style="padding:24px;">'
            f"<tr><td align=\"center\">"
            f'<table width="600" cellpadding="0" '
            f'cellspacing="0" style="{outer}">'
            f'<tr><td style="background:{color};'
            f'padding:16px 24px;">'
            f'<h2 style="margin:0;color:#fff;'
            f'font-size:18px;">'
            f"Argus Alert: {rule_name}</h2>"
            f"</td></tr>"
            f'<tr><td style="padding:24px;">'
            f'<table width="100%" cellpadding="4" '
            f'cellspacing="0" '
            f'style="font-size:14px;color:#333;">'
            f'<tr><td style="font-weight:bold;'
            f'width:100px;">Severity</td>'
            f"<td>{severity}</td></tr>"
            f'<tr><td style="font-weight:bold;">'
            f"Source</td><td>{source}</td></tr>"
            f'<tr><td style="font-weight:bold;">'
            f"Type</td><td>{event_type}</td></tr>"
            f'<tr><td style="font-weight:bold;">'
            f"Time</td><td>{timestamp}</td></tr>"
            f"</table>"
            f'<div style="{msg_style}">{message}</div>'
            f"</td></tr>"
            f'<tr><td style="padding:12px 24px;'
            f"background:#f8f9fa;"
            f'font-size:12px;color:#888;">'
            f"Alert ID: {alert_id}"
            f"</td></tr>"
            f"</table></td></tr></table>"
            f"</body></html>"
        )
