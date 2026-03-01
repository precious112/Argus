"""Billing REST endpoints (SaaS only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from argus_agent.auth.dependencies import require_role
from argus_agent.billing.plans import PLAN_LIMITS, USAGE_TIERS
from argus_agent.billing.polar_service import (
    create_checkout_session,
    create_customer_portal_session,
    get_subscription_status,
)
from argus_agent.billing.usage_guard import get_tenant_usage_summary
from argus_agent.config import get_settings

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans")
async def list_plans() -> dict[str, Any]:
    """List available plan tiers with limits and pricing (public)."""
    plans = []
    for key, limits in PLAN_LIMITS.items():
        plans.append({
            "id": key,
            "name": limits.name,
            "monthly_event_limit": limits.monthly_event_limit,
            "max_team_members": limits.max_team_members,
            "max_api_keys": limits.max_api_keys,
            "max_services": limits.max_services,
            "data_retention_days": limits.data_retention_days,
            "conversation_retention_days": limits.conversation_retention_days,
            "daily_ai_messages": limits.daily_ai_messages,
            "webhook_enabled": limits.webhook_enabled,
            "custom_dashboards": limits.custom_dashboards,
            "external_alert_channels": limits.external_alert_channels,
            "audit_log": limits.audit_log,
            "on_call_rotation": limits.on_call_rotation,
            "service_ownership": limits.service_ownership,
        })

    tiers = [
        {"up_to_events": ceiling, "price_dollars": price}
        for ceiling, price in USAGE_TIERS
    ]

    return {"plans": plans, "usage_tiers": tiers}


@router.get("/status")
async def billing_status(user: dict = Depends(require_role("owner", "admin"))) -> dict[str, Any]:
    """Current plan, subscription, and usage vs limits."""
    tenant_id = user.get("tenant_id", "default")

    usage = await get_tenant_usage_summary(tenant_id)
    subscription = await get_subscription_status(tenant_id)

    return {
        **usage,
        "subscription": subscription,
    }


@router.post("/checkout")
async def create_checkout(user: dict = Depends(require_role("owner", "admin"))) -> dict[str, str]:
    """Create a Polar checkout session for the Teams plan."""
    settings = get_settings()
    tenant_id = user.get("tenant_id", "default")

    success_url = f"{settings.deployment.frontend_url}/billing?upgraded=true"
    cancel_url = f"{settings.deployment.frontend_url}/billing"

    return await create_checkout_session(tenant_id, success_url, cancel_url)


@router.post("/portal")
async def customer_portal(user: dict = Depends(require_role("owner", "admin"))) -> dict[str, str]:
    """Create a Polar customer portal session for subscription management."""
    tenant_id = user.get("tenant_id", "default")
    return await create_customer_portal_session(tenant_id)
