"""Routes tool calls to remote SDK webhook handlers in SaaS mode.

When a SaaS tenant has configured a webhook with ``mode`` set to
``tool_execution`` or ``both``, host-level tools are dispatched to
the remote SDK instead of being executed locally on the agent server.
"""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.webhooks.dispatcher import dispatch_tool_call

logger = logging.getLogger("argus.webhooks.tool_router")

# Host-level tools that can be executed remotely via SDK webhook
HOST_TOOLS: set[str] = {
    "system_metrics",
    "process_list",
    "network_connections",
    "log_search",
    "log_tail",
    "file_read",
    "security_scan",
    "run_command",
}


def _is_saas() -> bool:
    """Check if running in SaaS deployment mode."""
    try:
        from argus_agent.config import get_settings
        return get_settings().deployment.mode == "saas"
    except Exception:
        return False


async def _get_active_webhook(
    tenant_id: str,
    tool_name: str,
) -> dict[str, Any] | None:
    """Find an active webhook configured for tool execution for this tenant.

    Returns a dict with url, secret, timeout_seconds, or None.
    """
    try:
        from sqlalchemy import select

        from argus_agent.storage.repositories import get_session
        from argus_agent.storage.saas_models import WebhookConfig

        async with get_session() as session:
            result = await session.execute(
                select(WebhookConfig).where(
                    WebhookConfig.tenant_id == tenant_id,
                    WebhookConfig.is_active.is_(True),
                    WebhookConfig.mode.in_(["tool_execution", "both"]),
                )
            )
            webhooks = result.scalars().all()

        for wh in webhooks:
            # Check if the webhook handles this specific tool
            if wh.remote_tools == "*" or tool_name in wh.remote_tools.split(","):
                return {
                    "url": wh.url,
                    "secret": wh.secret,
                    "timeout_seconds": wh.timeout_seconds,
                }

        return None
    except Exception:
        logger.debug("Failed to look up webhook for tenant %s", tenant_id, exc_info=True)
        return None


async def execute_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    tenant_id: str,
) -> dict[str, Any] | None:
    """Try to execute a tool via webhook. Returns None if not routed.

    When None is returned, the caller should fall back to local execution.
    """
    if not _is_saas():
        return None

    if tool_name not in HOST_TOOLS:
        return None

    webhook = await _get_active_webhook(tenant_id, tool_name)
    if not webhook:
        return None

    logger.info(
        "Routing tool %s to webhook %s (tenant=%s)",
        tool_name, webhook["url"], tenant_id,
    )

    result = await dispatch_tool_call(
        webhook_url=webhook["url"],
        webhook_secret=webhook["secret"],
        timeout_seconds=webhook["timeout_seconds"],
        tool_name=tool_name,
        tool_args=tool_args,
    )

    # If the webhook returned a result key, unwrap it
    if "result" in result and result.get("error") is None:
        return result["result"]

    # Return as-is (may contain error key)
    return result
