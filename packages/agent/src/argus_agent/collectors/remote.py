"""Shared helpers for remote data collection via webhooks in SaaS mode.

In SaaS mode, host-level collectors cannot use local psutil/filesystem
calls because the agent runs inside a Docker container — not on the
tenant's actual server.  All host data collection routes through the
SDK webhook handler running on the tenant's host.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("argus.collectors.remote")


async def get_webhook_tenants() -> list[dict[str, Any]]:
    """Query WebhookConfig for all tenants with active tool_execution webhooks.

    Returns a list of dicts with keys:
    ``tenant_id``, ``url``, ``secret``, ``timeout_seconds``.
    """
    try:
        from sqlalchemy import select

        from argus_agent.storage.repositories import get_session
        from argus_agent.storage.saas_models import WebhookConfig

        async with get_session() as session:
            result = await session.execute(
                select(WebhookConfig).where(
                    WebhookConfig.is_active.is_(True),
                    WebhookConfig.mode.in_(["tool_execution", "both"]),
                )
            )
            webhooks = result.scalars().all()

        tenants: list[dict[str, Any]] = []
        seen: set[str] = set()
        for wh in webhooks:
            if wh.tenant_id not in seen:
                seen.add(wh.tenant_id)
                tenants.append({
                    "tenant_id": wh.tenant_id,
                    "url": wh.url,
                    "secret": wh.secret,
                    "timeout_seconds": wh.timeout_seconds,
                })
        return tenants
    except Exception:
        logger.debug("Failed to query webhook tenants", exc_info=True)
        return []


async def execute_remote_tool(
    tenant_id: str,
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Call tool_router.execute_tool() for a specific tenant.

    Returns the tool result dict, or ``None`` on failure.
    """
    try:
        from argus_agent.webhooks.tool_router import execute_tool

        result = await execute_tool(
            tool_name=tool_name,
            tool_args=tool_args or {},
            tenant_id=tenant_id,
        )
        if result is None:
            return None
        if result.get("error"):
            logger.warning(
                "Remote tool %s failed for tenant %s: %s",
                tool_name, tenant_id, result["error"],
            )
            return None
        return result
    except Exception:
        logger.debug(
            "Remote tool %s failed for tenant %s",
            tool_name, tenant_id, exc_info=True,
        )
        return None
