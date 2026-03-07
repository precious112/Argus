"""Pay-As-You-Go budget management and Polar metered billing."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from argus_agent.billing.plans import PAYG_RATE_CENTS_PER_EVENT, get_plan_limits
from argus_agent.config import get_settings
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import Subscription, Tenant

logger = logging.getLogger("argus.billing.payg")


async def set_payg_budget(tenant_id: str, budget_cents: int) -> dict[str, Any]:
    """Enable/update PAYG budget. Set to 0 to disable.

    Returns the updated PAYG configuration.
    """
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            raise HTTPException(404, "Tenant not found")

        if tenant.plan == "free":
            raise HTTPException(
                403, "Pay-As-You-Go is only available on paid plans. Upgrade to Teams or Business."
            )

        if budget_cents < 0:
            raise HTTPException(400, "Budget must be >= 0")

        tenant.payg_enabled = budget_cents > 0
        tenant.payg_monthly_budget_cents = budget_cents
        tenant.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()

    return await get_payg_status(tenant_id)


async def get_payg_status(tenant_id: str) -> dict[str, Any]:
    """Return current PAYG state: enabled, budget, spend, remaining."""
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            return {
                "enabled": False,
                "budget_cents": 0,
                "spent_cents": 0,
                "remaining_cents": 0,
                "overage_events": 0,
                "rate_per_1k_cents": 30,
            }

        # Get billing period start
        result = await session.execute(
            select(Subscription)
            .where(
                Subscription.tenant_id == tenant_id,
                Subscription.status.in_(["active", "canceled"]),
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        sub = result.scalar_one_or_none()

    if sub and sub.current_period_start:
        period_start = sub.current_period_start
    else:
        now = datetime.now(UTC).replace(tzinfo=None)
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    limits = get_plan_limits(tenant.plan)

    # Count events in current billing period
    events_count = 0
    try:
        from argus_agent.storage.repositories import get_metrics_repository

        repo = get_metrics_repository()
        events_count = await asyncio.to_thread(repo.get_event_quota_count, tenant_id, period_start)
    except Exception:
        pass

    overage_events = max(0, events_count - limits.monthly_event_limit)
    spend_cents = round(overage_events * PAYG_RATE_CENTS_PER_EVENT, 2)
    budget_cents = tenant.payg_monthly_budget_cents
    remaining = max(0, budget_cents - spend_cents) if tenant.payg_enabled else 0

    return {
        "enabled": tenant.payg_enabled,
        "budget_cents": budget_cents,
        "spent_cents": spend_cents,
        "remaining_cents": round(remaining, 2),
        "overage_events": overage_events,
        "rate_per_1k_cents": 30,
    }


async def report_payg_events_to_polar(tenant_id: str, overage_events: int) -> None:
    """Report overage event count to Polar meter for end-of-cycle invoicing.

    This is a best-effort operation — failures are logged but don't block ingest.
    """
    settings = get_settings()
    meter_id = settings.deployment.polar_payg_meter_id
    if not meter_id:
        return

    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant or not tenant.polar_customer_id:
            return

    try:
        from argus_agent.billing.polar_service import _get_polar_client

        polar = _get_polar_client()
        polar.events.ingest(
            request={
                "events": [
                    {
                        "customer_id": tenant.polar_customer_id,
                        "name": "payg_overage_events",
                        "metadata": {"count": overage_events},
                    }
                ],
            }
        )
    except Exception:
        logger.warning("Failed to report PAYG events to Polar for %s", tenant_id, exc_info=True)
