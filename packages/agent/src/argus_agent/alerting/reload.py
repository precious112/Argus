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
    """Read enabled channel configs from DB and update the running AlertEngine.

    WebSocketChannel goes to the engine (immediate, unfiltered).
    External channels (Slack, Email, Webhook) go to the formatter (severity-routed).
    """
    from argus_agent.api.ws import manager
    from argus_agent.main import _get_alert_engine, _get_alert_formatter

    engine = _get_alert_engine()
    if engine is None:
        logger.warning("reload_channels called but AlertEngine is not initialised")
        return

    svc = NotificationSettingsService()
    configs = await svc.get_all_raw()

    # WebSocket always goes directly to the engine
    engine.set_channels([WebSocketChannel(manager)])

    external: list[SlackChannel | EmailChannel | WebhookChannel] = []

    for row in configs:
        if not row["enabled"]:
            continue
        cfg = row["config"]
        ctype = row["channel_type"]

        if ctype == "slack":
            external.append(SlackChannel(
                bot_token=cfg.get("bot_token", ""),
                channel_id=cfg.get("channel_id", ""),
            ))
        elif ctype == "email":
            external.append(EmailChannel(
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
                external.append(WebhookChannel(urls))

    # External channels route through the formatter (severity-based batching)
    formatter = _get_alert_formatter()
    if formatter is not None:
        formatter.set_channels(external)
    else:
        logger.debug("No formatter available, external channels not set")

    total = 1 + len(external)  # 1 for WebSocket
    logger.info("Reloaded %d notification channel(s) from DB", total)
