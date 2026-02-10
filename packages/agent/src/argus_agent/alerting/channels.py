"""Notification channels: WebSocket, webhook, email."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from argus_agent.api.protocol import AlertMessage, ServerMessage, ServerMessageType

logger = logging.getLogger("argus.alerting.channels")


class NotificationChannel(ABC):
    """Base class for alert notification channels."""

    @abstractmethod
    async def send(self, alert: Any, event: Any) -> bool:
        """Send a notification for the given alert/event. Returns True on success."""
        ...


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


class EmailChannel(NotificationChannel):
    """Sends alert emails via SMTP. Only active when email is configured."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_addr: str,
        to_addrs: list[str],
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._from_addr = from_addr
        self._to_addrs = to_addrs

    async def send(self, alert: Any, event: Any) -> bool:
        if not self._to_addrs:
            return True

        try:
            from email.message import EmailMessage

            import aiosmtplib

            title = f"[Argus {alert.severity}] {alert.rule_name}"
            body = (
                f"Alert: {alert.rule_name}\n"
                f"Severity: {alert.severity}\n"
                f"Source: {event.source}\n"
                f"Time: {alert.timestamp.isoformat()}\n\n"
                f"{event.message or 'No details available'}"
            )

            msg = EmailMessage()
            msg["Subject"] = title
            msg["From"] = self._from_addr
            msg["To"] = ", ".join(self._to_addrs)
            msg.set_content(body)

            await aiosmtplib.send(
                msg,
                hostname=self._smtp_host,
                port=self._smtp_port,
            )
            return True
        except Exception:
            logger.exception("Email notification failed")
            return False
