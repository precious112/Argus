"""Billing REST endpoints (SaaS only)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from argus_agent.auth.dependencies import require_role
from argus_agent.billing.payg import get_credit_status
from argus_agent.billing.plans import PLAN_LIMITS, PLAN_PRICING
from argus_agent.billing.polar_service import (
    create_checkout_session,
    create_credit_checkout_session,
    create_customer_portal_session,
    get_subscription_status,
    upgrade_subscription,
)
from argus_agent.billing.usage_guard import get_tenant_usage_summary
from argus_agent.config import get_settings

logger = logging.getLogger("argus.api.billing")

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan_id: str = "teams"
    billing_interval: str = "month"


class CreditCheckoutRequest(BaseModel):
    amount_dollars: float


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
            "model": "prepaid_credits",
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
) -> dict[str, Any]:
    """Create a Polar checkout session, or upgrade an existing subscription."""
    settings = get_settings()
    tenant_id = user.get("tenant_id", "default")

    plan_id = body.plan_id if body else "teams"
    billing_interval = body.billing_interval if body else "month"

    if plan_id not in ("teams", "business"):
        plan_id = "teams"
    if billing_interval not in ("month", "year"):
        billing_interval = "month"

    # Check for existing active subscription
    existing = await get_subscription_status(tenant_id)
    if existing and existing["status"] == "active" and existing["plan_id"] != plan_id:
        try:
            return await upgrade_subscription(
                tenant_id, plan_id, billing_interval=billing_interval,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            logger.exception("Upgrade failed for tenant %s", tenant_id)
            raise HTTPException(status_code=502, detail="Failed to upgrade subscription")

    success_url = f"{settings.deployment.frontend_url}/billing?upgraded=true"

    try:
        return await create_checkout_session(
            tenant_id, success_url,
            plan_id=plan_id, billing_interval=billing_interval,
        )
    except Exception:
        logger.exception("Checkout failed for tenant %s", tenant_id)
        raise HTTPException(status_code=502, detail="Failed to create checkout session")


@router.post("/portal")
async def customer_portal(user: dict = Depends(require_role("owner", "admin"))) -> dict[str, str]:
    """Create a Polar customer portal session for subscription management."""
    tenant_id = user.get("tenant_id", "default")
    try:
        return await create_customer_portal_session(tenant_id)
    except Exception:
        logger.exception("Portal session failed for tenant %s", tenant_id)
        raise HTTPException(status_code=502, detail="Failed to create portal session")


@router.get("/credits")
async def get_credits(user: dict = Depends(require_role("owner", "admin"))) -> dict[str, Any]:
    """Get current credit balance and recent transactions."""
    tenant_id = user.get("tenant_id", "default")
    return await get_credit_status(tenant_id)


@router.post("/credits/checkout")
async def create_credit_checkout(
    body: CreditCheckoutRequest,
    user: dict = Depends(require_role("owner", "admin")),
) -> dict[str, Any]:
    """Create a Polar checkout to purchase prepaid credits."""
    settings = get_settings()
    tenant_id = user.get("tenant_id", "default")

    if body.amount_dollars < 5:
        raise HTTPException(400, "Minimum credit purchase is $5")
    if body.amount_dollars > 500:
        raise HTTPException(400, "Maximum credit purchase is $500")

    amount_cents = int(body.amount_dollars * 100)
    success_url = f"{settings.deployment.frontend_url}/billing?credits_purchased=true"

    try:
        return await create_credit_checkout_session(tenant_id, amount_cents, success_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        logger.exception("Credit checkout failed for tenant %s", tenant_id)
        raise HTTPException(502, "Failed to create credit checkout session")
