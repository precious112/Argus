"""Onboarding API — track new user setup progress."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select

from argus_agent.auth.dependencies import get_current_user
from argus_agent.storage.models import AppConfig
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import ApiKey, WebhookConfig

logger = logging.getLogger("argus.onboarding")

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/status")
async def onboarding_status(user: dict = Depends(get_current_user)):
    """Return the current onboarding progress for the tenant."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        # Check if they have an API key
        keys = await session.execute(
            select(ApiKey).where(
                ApiKey.tenant_id == tenant_id,
                ApiKey.is_active.is_(True),
            )
        )
        has_api_key = keys.scalar_one_or_none() is not None

        # Check if they have a webhook config
        webhooks = await session.execute(
            select(WebhookConfig).where(
                WebhookConfig.tenant_id == tenant_id,
                WebhookConfig.is_active.is_(True),
            )
        )
        has_webhook = webhooks.scalar_one_or_none() is not None

        # Check if they've dismissed onboarding
        dismissed = await session.execute(
            select(AppConfig).where(
                AppConfig.key == "onboarding_dismissed",
                AppConfig.tenant_id == tenant_id,
            )
        )
        is_dismissed = dismissed.scalar_one_or_none() is not None

    steps = {
        "create_api_key": has_api_key,
        "install_sdk": has_api_key,  # Proxy: if they have a key, they've seen SDK instructions
        "configure_webhook": has_webhook,
    }

    return {
        "dismissed": is_dismissed,
        "completed": all(steps.values()),
        "steps": steps,
    }


@router.post("/dismiss")
async def dismiss_onboarding(user: dict = Depends(get_current_user)):
    """Mark onboarding as dismissed for this tenant."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        existing = await session.execute(
            select(AppConfig).where(
                AppConfig.key == "onboarding_dismissed",
                AppConfig.tenant_id == tenant_id,
            )
        )
        if not existing.scalar_one_or_none():
            config = AppConfig(
                key="onboarding_dismissed",
                tenant_id=tenant_id,
                value="true",
            )
            session.add(config)
            await session.commit()

    return {"status": "ok"}
