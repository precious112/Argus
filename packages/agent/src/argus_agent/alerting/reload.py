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
    from argus_agent.main import _get_alert_engine, _get_alert_formatter, _get_distributed_manager

    engine = _get_alert_engine()
    if engine is None:
        logger.warning("reload_channels called but AlertEngine is not initialised")
        return

    svc = NotificationSettingsService()
    configs = await svc.get_all_raw()

    # Use distributed manager in SaaS mode for cross-pod alert delivery
    ws_mgr = _get_distributed_manager() or manager
    engine.set_channels([WebSocketChannel(ws_mgr)])

    external: list[SlackChannel | EmailChannel | WebhookChannel] = []

    # In SaaS mode, check for OAuth Slack installation (takes priority over manual config)
    oauth_slack_used = False
    from argus_agent.config import get_settings as _get_settings
    if _get_settings().deployment.mode == "saas":
        try:
            from argus_agent.integrations.slack_oauth import decrypt_bot_token, get_installation
            from argus_agent.tenancy.context import get_tenant_id
            tenant_id = get_tenant_id()
            install = await get_installation(tenant_id)
            if install and install.default_channel_id:
                bot_token = decrypt_bot_token(install)
                if bot_token:
                    external.append(SlackChannel(
                        bot_token=bot_token,
                        channel_id=install.default_channel_id,
                    ))
                    oauth_slack_used = True
                    logger.debug("Using OAuth Slack install for tenant %s", tenant_id)
        except Exception:
            logger.debug("No OAuth Slack install available, falling back to manual config")

    for row in configs:
        if not row["enabled"]:
            continue
        cfg = row["config"]
        ctype = row["channel_type"]

        if ctype == "slack":
            # Skip manual Slack config if OAuth install is active
            if oauth_slack_used:
                continue
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
