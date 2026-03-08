"""Webhook configuration CRUD endpoints (SaaS only)."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from argus_agent.auth.dependencies import require_role
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import WebhookConfig

logger = logging.getLogger("argus.api.webhook_config")

router = APIRouter(prefix="/webhooks/config", tags=["webhook-config"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class CreateWebhookRequest(BaseModel):
    name: str = ""
    url: str
    secret: str = ""  # auto-generated if empty
    events: str = "*"
    mode: str = "alerts_only"
    remote_tools: str = "*"
    timeout_seconds: int = 30


class UpdateWebhookRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    secret: str | None = None
    events: str | None = None
    mode: str | None = None
    remote_tools: str | None = None
    timeout_seconds: int | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "URL must use http or https scheme")
    if not parsed.netloc:
        raise HTTPException(400, "URL must have a valid host")


def _validate_mode(mode: str) -> None:
    if mode not in ("alerts_only", "tool_execution", "both"):
        raise HTTPException(400, "mode must be 'alerts_only', 'tool_execution', or 'both'")


def _webhook_dict(wh: WebhookConfig) -> dict:
    return {
        "id": wh.id,
        "name": wh.name,
        "url": wh.url,
        "events": wh.events,
        "mode": wh.mode,
        "remote_tools": wh.remote_tools,
        "timeout_seconds": wh.timeout_seconds,
        "is_active": wh.is_active,
        "last_ping_at": wh.last_ping_at.isoformat() if wh.last_ping_at else None,
        "last_ping_status": wh.last_ping_status,
        "created_at": wh.created_at.isoformat() if wh.created_at else None,
        "updated_at": wh.updated_at.isoformat() if wh.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_webhooks(user: dict = Depends(require_role("owner", "admin"))):
    """List webhook configurations for the current tenant."""
    tenant_id = user.get("tenant_id", "default")
    async with get_session() as session:
        result = await session.execute(
            select(WebhookConfig).where(WebhookConfig.tenant_id == tenant_id)
        )
        webhooks = result.scalars().all()
    return [_webhook_dict(wh) for wh in webhooks]


@router.post("")
async def create_webhook(
    body: CreateWebhookRequest,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Create a new webhook configuration."""
    _validate_url(body.url)
    _validate_mode(body.mode)

    tenant_id = user.get("tenant_id", "default")
    webhook_secret = body.secret or secrets.token_hex(32)

    wh = WebhookConfig(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        name=body.name,
        url=body.url,
        secret=webhook_secret,
        events=body.events,
        mode=body.mode,
        remote_tools=body.remote_tools,
        timeout_seconds=body.timeout_seconds,
    )

    async with get_session() as session:
        session.add(wh)
        await session.commit()

    logger.info("Webhook created: %s for tenant %s", wh.id, tenant_id)
    result = _webhook_dict(wh)
    # Include the secret only on creation so the user can copy it
    result["secret"] = webhook_secret
    return result


@router.put("/{webhook_id}")
async def update_webhook(
    webhook_id: str,
    body: UpdateWebhookRequest,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Update an existing webhook configuration."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(WebhookConfig).where(
                WebhookConfig.id == webhook_id,
                WebhookConfig.tenant_id == tenant_id,
            )
        )
        wh = result.scalar_one_or_none()
        if not wh:
            raise HTTPException(404, "Webhook not found")

        if body.url is not None:
            _validate_url(body.url)
            wh.url = body.url
        if body.name is not None:
            wh.name = body.name
        if body.secret is not None:
            wh.secret = body.secret
        if body.events is not None:
            wh.events = body.events
        if body.mode is not None:
            _validate_mode(body.mode)
            wh.mode = body.mode
        if body.remote_tools is not None:
            wh.remote_tools = body.remote_tools
        if body.timeout_seconds is not None:
            wh.timeout_seconds = body.timeout_seconds
        if body.is_active is not None:
            wh.is_active = body.is_active

        wh.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()
        await session.refresh(wh)

    logger.info("Webhook updated: %s for tenant %s", webhook_id, tenant_id)
    return _webhook_dict(wh)


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Delete a webhook configuration."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(WebhookConfig).where(
                WebhookConfig.id == webhook_id,
                WebhookConfig.tenant_id == tenant_id,
            )
        )
        wh = result.scalar_one_or_none()
        if not wh:
            raise HTTPException(404, "Webhook not found")
        await session.delete(wh)
        await session.commit()

    logger.info("Webhook deleted: %s for tenant %s", webhook_id, tenant_id)
    return {"status": "ok"}


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: str,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Send a test ping to the webhook URL and record the result."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(WebhookConfig).where(
                WebhookConfig.id == webhook_id,
                WebhookConfig.tenant_id == tenant_id,
            )
        )
        wh = result.scalar_one_or_none()
        if not wh:
            raise HTTPException(404, "Webhook not found")

        from argus_agent.webhooks.dispatcher import ping_webhook

        success, status = await ping_webhook(
            webhook_url=wh.url,
            webhook_secret=wh.secret,
            timeout_seconds=min(wh.timeout_seconds, 10),
        )

        wh.last_ping_at = datetime.now(UTC).replace(tzinfo=None)
        wh.last_ping_status = status
        wh.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()

    return {"success": success, "status": status}
