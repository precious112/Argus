"""Slack OAuth integration API — connect, disconnect, manage channels."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from argus_agent.auth.dependencies import require_role
from argus_agent.config import get_settings
from argus_agent.integrations.slack_oauth import (
    disconnect as slack_disconnect,
)
from argus_agent.integrations.slack_oauth import (
    exchange_code,
    get_authorize_url,
    get_installation,
)
from argus_agent.integrations.slack_oauth import (
    list_channels as slack_list_channels,
)
from argus_agent.integrations.slack_oauth import (
    test_connection as slack_test_connection,
)
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import SlackInstallation

logger = logging.getLogger("argus.api.slack_integration")

router = APIRouter(prefix="/integrations/slack", tags=["integrations"])


@router.get("/status")
async def slack_status(user: dict = Depends(require_role("owner", "admin"))):
    """Get the current Slack connection status."""
    tenant_id = user.get("tenant_id", "default")
    install = await get_installation(tenant_id)
    if not install:
        return {"connected": False}
    return {
        "connected": True,
        "team_name": install.team_name,
        "team_id": install.team_id,
        "channel_id": install.default_channel_id,
        "channel_name": install.default_channel_name,
    }


@router.get("/authorize")
async def slack_authorize(user: dict = Depends(require_role("owner", "admin"))):
    """Get the Slack OAuth authorization URL."""
    tenant_id = user.get("tenant_id", "default")
    user_id = user.get("sub", "")
    url = get_authorize_url(tenant_id, user_id)
    return {"url": url}


@router.get("/callback")
async def slack_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle Slack OAuth callback — exchange code, store install, redirect."""
    settings = get_settings()
    try:
        await exchange_code(code, state)
    except ValueError as exc:
        logger.warning("Slack OAuth callback failed: %s", exc)
        return RedirectResponse(
            f"{settings.deployment.frontend_url}/integrations?slack=error",
            status_code=302,
        )

    return RedirectResponse(
        f"{settings.deployment.frontend_url}/integrations?slack=connected",
        status_code=302,
    )


@router.post("/disconnect")
async def slack_disconnect_endpoint(user: dict = Depends(require_role("owner", "admin"))):
    """Disconnect Slack integration."""
    tenant_id = user.get("tenant_id", "default")
    await slack_disconnect(tenant_id)
    return {"status": "disconnected"}


@router.get("/channels")
async def slack_channels(user: dict = Depends(require_role("owner", "admin"))):
    """List Slack workspace channels."""
    tenant_id = user.get("tenant_id", "default")
    channels = await slack_list_channels(tenant_id)
    return {"channels": channels}


class ChannelUpdate(BaseModel):
    channel_id: str
    channel_name: str


@router.post("/channel")
async def slack_update_channel(
    body: ChannelUpdate,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Update the default alert channel."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(SlackInstallation).where(
                SlackInstallation.tenant_id == tenant_id,
                SlackInstallation.is_active.is_(True),
            )
        )
        install = result.scalar_one_or_none()
        if not install:
            return {"error": "not_installed"}, 404

        install.default_channel_id = body.channel_id
        install.default_channel_name = body.channel_name
        await session.commit()

    return {"status": "ok", "channel_id": body.channel_id, "channel_name": body.channel_name}


@router.post("/test")
async def slack_test(user: dict = Depends(require_role("owner", "admin"))):
    """Send a test message to the configured Slack channel."""
    tenant_id = user.get("tenant_id", "default")
    result = await slack_test_connection(tenant_id)
    return result
