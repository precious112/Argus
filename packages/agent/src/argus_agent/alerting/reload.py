"""Runtime reload of notification channels from DB config."""

from __future__ import annotations

import logging

from argus_agent.alerting.channels import (
    EmailChannel,
    SlackChannel,
    WebhookChannel,
    WebSocketChannel,
)
from argus_agent.alerting.settings import NotificationSettingsService

logger = logging.getLogger("argus.alerting.reload")


async def reload_channels() -> None:
    """Read enabled channel configs from DB and update the running AlertEngine."""
    from argus_agent.api.ws import manager
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        logger.warning("reload_channels called but AlertEngine is not initialised")
        return

    svc = NotificationSettingsService()
    configs = await svc.get_all_raw()

    channels: list[WebSocketChannel | SlackChannel | EmailChannel | WebhookChannel] = [
        WebSocketChannel(manager),
    ]

    for row in configs:
        if not row["enabled"]:
            continue
        cfg = row["config"]
        ctype = row["channel_type"]

        if ctype == "slack":
            channels.append(SlackChannel(
                bot_token=cfg.get("bot_token", ""),
                channel_id=cfg.get("channel_id", ""),
            ))
        elif ctype == "email":
            channels.append(EmailChannel(
                smtp_host=cfg.get("smtp_host", ""),
                smtp_port=cfg.get("smtp_port", 587),
                from_addr=cfg.get("from_addr", ""),
                to_addrs=cfg.get("to_addrs", []),
                smtp_user=cfg.get("smtp_user", ""),
                smtp_password=cfg.get("smtp_password", ""),
                use_tls=cfg.get("use_tls", True),
            ))
        elif ctype == "webhook":
            urls = cfg.get("urls", [])
            if urls:
                channels.append(WebhookChannel(urls))

    engine.set_channels(channels)
    logger.info("Reloaded %d notification channel(s) from DB", len(channels))
