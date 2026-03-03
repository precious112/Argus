"""Billing REST endpoints (SaaS only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from argus_agent.auth.dependencies import require_role
from argus_agent.billing.payg import get_payg_status, set_payg_budget
from argus_agent.billing.plans import PLAN_LIMITS, PLAN_PRICING
from argus_agent.billing.polar_service import (
    create_checkout_session,
    create_customer_portal_session,
    get_subscription_status,
)
from argus_agent.billing.usage_guard import get_tenant_usage_summary
from argus_agent.config import get_settings

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan_id: str = "teams"
    billing_interval: str = "month"


class PaygBudgetRequest(BaseModel):
    budget_dollars: float = 0.0


@router.get("/plans")
async def list_plans() -> dict[str, Any]:
    """List available plan tiers with limits, pricing, and PAYG info."""
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

    pricing = {
        plan_id: {
            "monthly": prices["monthly_cents"] / 100,
            "annual": prices["annual_cents"] / 100,
        }
        for plan_id, prices in PLAN_PRICING.items()
    }

    return {
        "plans": plans,
        "pricing": pricing,
        "payg": {
            "rate_per_1k_dollars": 0.30,
            "available_on": ["teams", "business"],
        },
    }


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
async def create_checkout(
    body: CheckoutRequest | None = None,
    user: dict = Depends(require_role("owner", "admin")),
) -> dict[str, str]:
    """Create a Polar checkout session for the specified plan and interval."""
    settings = get_settings()
    tenant_id = user.get("tenant_id", "default")

    plan_id = body.plan_id if body else "teams"
    billing_interval = body.billing_interval if body else "month"

    if plan_id not in ("teams", "business"):
        plan_id = "teams"
    if billing_interval not in ("month", "year"):
        billing_interval = "month"

    success_url = f"{settings.deployment.frontend_url}/billing?upgraded=true"
    cancel_url = f"{settings.deployment.frontend_url}/billing"

    return await create_checkout_session(
        tenant_id, success_url, cancel_url,
        plan_id=plan_id, billing_interval=billing_interval,
    )


@router.post("/portal")
async def customer_portal(user: dict = Depends(require_role("owner", "admin"))) -> dict[str, str]:
    """Create a Polar customer portal session for subscription management."""
    tenant_id = user.get("tenant_id", "default")
    return await create_customer_portal_session(tenant_id)


@router.get("/payg")
async def get_payg(user: dict = Depends(require_role("owner", "admin"))) -> dict[str, Any]:
    """Get current PAYG configuration and spend."""
    tenant_id = user.get("tenant_id", "default")
    status = await get_payg_status(tenant_id)
    return {
        "enabled": status["enabled"],
        "budget_dollars": status["budget_cents"] / 100,
        "spent_dollars": status["spent_cents"] / 100,
        "remaining_dollars": status["remaining_cents"] / 100,
        "overage_events": status["overage_events"],
        "rate_per_1k_dollars": 0.30,
    }


@router.put("/payg")
async def update_payg(
    body: PaygBudgetRequest,
    user: dict = Depends(require_role("owner", "admin")),
) -> dict[str, Any]:
    """Set PAYG budget. Set budget_dollars to 0 to disable."""
    tenant_id = user.get("tenant_id", "default")
    budget_cents = int(body.budget_dollars * 100)
    result = await set_payg_budget(tenant_id, budget_cents)
    return {
        "enabled": result["enabled"],
        "budget_dollars": result["budget_cents"] / 100,
        "spent_dollars": result["spent_cents"] / 100,
        "remaining_dollars": result["remaining_cents"] / 100,
        "overage_events": result["overage_events"],
    }
