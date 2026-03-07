"""FastAPI dependencies that enforce plan limits in SaaS mode."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import func, select

from argus_agent.billing.plans import (
    PAYG_RATE_CENTS_PER_EVENT,
    get_plan_limits,
)
from argus_agent.config import get_settings
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import (
    ApiKey,
    Subscription,
    TeamMember,
    Tenant,
    UsageNotification,
)

logger = logging.getLogger("argus.billing.guard")


def _is_saas() -> bool:
    return get_settings().deployment.mode == "saas"


async def _get_tenant_plan(tenant_id: str) -> str:
    """Look up the tenant's current plan."""
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        return tenant.plan if tenant else "free"


async def _get_tenant_and_subscription(
    tenant_id: str,
) -> tuple[Tenant | None, Subscription | None]:
    """Fetch tenant and latest active subscription in one session."""
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
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
        return tenant, sub


def _billing_period_start(sub: Subscription | None) -> datetime:
    """Return the start of the current billing period."""
    if sub and sub.current_period_start:
        return sub.current_period_start
    now = datetime.now(UTC).replace(tzinfo=None)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def check_team_member_limit(request: Request) -> None:
    """Raise 403 if the tenant has reached their team member limit."""
    if not _is_saas():
        return

    user: dict[str, Any] = getattr(request.state, "user", {})
    tenant_id = user.get("tenant_id", "default")
    plan = await _get_tenant_plan(tenant_id)
    limits = get_plan_limits(plan)

    async with get_session() as session:
        result = await session.execute(
            select(func.count()).select_from(TeamMember).where(
                TeamMember.tenant_id == tenant_id
            )
        )
        count = result.scalar() or 0

    if count >= limits.max_team_members:
        raise HTTPException(
            403,
            f"Team member limit reached ({count}/{limits.max_team_members}). "
            "Upgrade your plan for more team members.",
        )


async def check_api_key_limit(request: Request) -> None:
    """Raise 403 if the tenant has reached their API key limit."""
    if not _is_saas():
        return

    user: dict[str, Any] = getattr(request.state, "user", {})
    tenant_id = user.get("tenant_id", "default")
    plan = await _get_tenant_plan(tenant_id)
    limits = get_plan_limits(plan)

    async with get_session() as session:
        result = await session.execute(
            select(func.count()).select_from(ApiKey).where(
                ApiKey.tenant_id == tenant_id,
                ApiKey.is_active.is_(True),
            )
        )
        count = result.scalar() or 0

    if count >= limits.max_api_keys:
        raise HTTPException(
            403,
            f"API key limit reached ({count}/{limits.max_api_keys}). "
            "Upgrade your plan for more API keys.",
        )


async def check_event_ingest_limit(tenant_id: str, *, batch_size: int = 1) -> None:
    """Check quota; allow if under plan limit. If over, check PAYG budget."""
    if not _is_saas():
        return

    try:
        tenant, subscription = await _get_tenant_and_subscription(tenant_id)
        plan = tenant.plan if tenant else "free"
        limits = get_plan_limits(plan)

        period_start = _billing_period_start(subscription)

        from argus_agent.storage.repositories import get_metrics_repository

        repo = get_metrics_repository()
        event_count = await asyncio.to_thread(repo.get_event_quota_count, tenant_id, period_start)
    except Exception:
        logger.warning("Could not check event count, rejecting ingest", exc_info=True)
        raise HTTPException(503, "Billing check unavailable, try again")

    # Under plan quota (accounting for batch size) → allow
    if event_count + batch_size <= limits.monthly_event_limit:
        asyncio.ensure_future(
            _check_quota_thresholds(
                tenant_id, event_count, limits.monthly_event_limit, period_start,
            )
        )
        return

    # Over plan quota — check PAYG
    if not tenant or not tenant.payg_enabled or tenant.payg_monthly_budget_cents <= 0:
        raise HTTPException(
            429,
            f"Monthly event limit reached ({event_count:,}/{limits.monthly_event_limit:,}). "
            "Enable Pay-As-You-Go or upgrade your plan.",
        )

    # Calculate PAYG spend
    overage_events = event_count - limits.monthly_event_limit
    payg_spend_cents = overage_events * PAYG_RATE_CENTS_PER_EVENT
    budget_cents = tenant.payg_monthly_budget_cents

    if payg_spend_cents >= budget_cents:
        raise HTTPException(
            429,
            f"PAYG budget exhausted (${payg_spend_cents / 100:.2f}/${budget_cents / 100:.2f}). "
            "Increase your PAYG budget to continue ingesting events.",
        )

    # Under PAYG budget → allow, report to Polar + check thresholds (fire-and-forget)
    from argus_agent.billing.payg import report_payg_events_to_polar

    asyncio.ensure_future(
        report_payg_events_to_polar(tenant_id, batch_size)
    )
    asyncio.ensure_future(
        _check_payg_thresholds(tenant_id, payg_spend_cents, budget_cents, period_start)
    )


async def check_ai_message_limit(request: Request) -> None:
    """Raise 429 if the free-tier tenant has used all daily AI messages."""
    if not _is_saas():
        return

    user: dict[str, Any] = getattr(request.state, "user", {})
    tenant_id = user.get("tenant_id", "default")
    plan = await _get_tenant_plan(tenant_id)
    limits = get_plan_limits(plan)

    if limits.daily_ai_messages < 0:
        return  # unlimited

    try:
        from argus_agent.storage.token_usage import TokenUsageService

        svc = TokenUsageService()
        now = datetime.now(UTC).replace(tzinfo=None)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        summary = await svc.get_usage_over_time(
            granularity="day",
            since=start_of_day,
        )
        count = sum(row.get("request_count", 0) for row in summary)
    except Exception:
        logger.debug("Could not check AI message count, allowing", exc_info=True)
        return

    if count >= limits.daily_ai_messages:
        raise HTTPException(
            429,
            f"Daily AI message limit reached ({count}/{limits.daily_ai_messages}). "
            "Upgrade to Teams for unlimited AI messages.",
        )


async def get_tenant_usage_summary(tenant_id: str) -> dict[str, Any]:
    """Return current usage counts vs plan limits for the tenant."""
    tenant, subscription = await _get_tenant_and_subscription(tenant_id)
    plan = tenant.plan if tenant else "free"
    limits = get_plan_limits(plan)
    period_start = _billing_period_start(subscription)
    period_end = subscription.current_period_end if subscription else None

    members_count = 0
    keys_count = 0
    async with get_session() as session:
        result = await session.execute(
            select(func.count()).select_from(TeamMember).where(
                TeamMember.tenant_id == tenant_id
            )
        )
        members_count = result.scalar() or 0

        result = await session.execute(
            select(func.count()).select_from(ApiKey).where(
                ApiKey.tenant_id == tenant_id,
                ApiKey.is_active.is_(True),
            )
        )
        keys_count = result.scalar() or 0

    # Event count (best-effort)
    events_count = 0
    try:
        from argus_agent.storage.repositories import get_metrics_repository

        repo = get_metrics_repository()
        events_count = await asyncio.to_thread(repo.get_event_quota_count, tenant_id, period_start)
    except Exception:
        pass

    # Compute PAYG fields
    overage_events = max(0, events_count - limits.monthly_event_limit)
    payg_spend_cents = overage_events * PAYG_RATE_CENTS_PER_EVENT
    payg_enabled = tenant.payg_enabled if tenant else False
    payg_budget_cents = tenant.payg_monthly_budget_cents if tenant else 0

    return {
        "plan": plan,
        "plan_name": limits.name,
        "team_members": {"current": members_count, "limit": limits.max_team_members},
        "api_keys": {"current": keys_count, "limit": limits.max_api_keys},
        "monthly_events": {"current": events_count, "limit": limits.monthly_event_limit},
        "max_services": limits.max_services,
        "data_retention_days": limits.data_retention_days,
        "conversation_retention_days": limits.conversation_retention_days,
        "daily_ai_messages": limits.daily_ai_messages,
        "billing_period_start": period_start.isoformat(),
        "billing_period_end": period_end.isoformat() if period_end else None,
        "payg": {
            "enabled": payg_enabled,
            "budget_cents": payg_budget_cents,
            "spent_cents": round(payg_spend_cents, 2),
            "overage_events": overage_events,
            "rate_per_1k_cents": 30,
        },
        "features": {
            "webhook_enabled": limits.webhook_enabled,
            "custom_dashboards": limits.custom_dashboards,
            "external_alert_channels": limits.external_alert_channels,
            "audit_log": limits.audit_log,
            "on_call_rotation": limits.on_call_rotation,
            "service_ownership": limits.service_ownership,
        },
    }


# ---------------------------------------------------------------------------
# Threshold notification helpers
# ---------------------------------------------------------------------------

async def _has_notification_been_sent(
    tenant_id: str, threshold: str, period_start: datetime
) -> bool:
    """Check if a notification has already been sent for this threshold/cycle."""
    async with get_session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(UsageNotification)
            .where(
                UsageNotification.tenant_id == tenant_id,
                UsageNotification.threshold == threshold,
                UsageNotification.billing_period_start == period_start,
            )
        )
        return (result.scalar() or 0) > 0


async def _record_notification(
    tenant_id: str, threshold: str, period_start: datetime
) -> None:
    """Record that a threshold notification was sent."""
    async with get_session() as session:
        session.add(
            UsageNotification(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                billing_period_start=period_start,
                threshold=threshold,
            )
        )
        await session.commit()


async def _get_tenant_owner_emails(tenant_id: str) -> list[str]:
    """Get email addresses for tenant owners/admins."""
    from argus_agent.storage.models import User

    async with get_session() as session:
        result = await session.execute(
            select(User.email)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(
                TeamMember.tenant_id == tenant_id,
                TeamMember.role.in_(["owner", "admin"]),
                User.email.isnot(None),
                User.email != "",
            )
        )
        return [row[0] for row in result.all()]


async def _send_threshold_notification(
    tenant_id: str, threshold: str, period_start: datetime, **kwargs: Any
) -> None:
    """Send a threshold notification email if not already sent this cycle."""
    if await _has_notification_been_sent(tenant_id, threshold, period_start):
        return

    await _record_notification(tenant_id, threshold, period_start)

    try:
        emails = await _get_tenant_owner_emails(tenant_id)
        if not emails:
            return

        # Get tenant name
        async with get_session() as session:
            tenant = await session.get(Tenant, tenant_id)
            tenant_name = tenant.name if tenant else "Your organization"

        from argus_agent.auth.email import send_usage_notification_email

        for email in emails:
            await send_usage_notification_email(
                to=email,
                tenant_name=tenant_name,
                threshold=threshold,
                **kwargs,
            )
    except Exception:
        logger.debug("Failed to send threshold notification %s", threshold, exc_info=True)


async def _check_quota_thresholds(
    tenant_id: str, event_count: int, limit: int, period_start: datetime
) -> None:
    """Check and fire quota threshold notifications."""
    if limit <= 0:
        return

    ratio = event_count / limit

    if ratio >= 1.0:
        # Fetch PAYG status to include in notification
        async with get_session() as session:
            tenant = await session.get(Tenant, tenant_id)
        payg_enabled = tenant.payg_enabled if tenant else False
        await _send_threshold_notification(
            tenant_id, "quota_100", period_start,
            current=event_count, limit=limit, payg_enabled=payg_enabled,
        )
    elif ratio >= 0.80:
        await _send_threshold_notification(
            tenant_id, "quota_80", period_start,
            current=event_count, limit=limit,
        )


async def _check_payg_thresholds(
    tenant_id: str, spend_cents: float, budget_cents: int, period_start: datetime
) -> None:
    """Check and fire PAYG budget threshold notifications."""
    if budget_cents <= 0:
        return

    ratio = spend_cents / budget_cents
    budget_str = f"{budget_cents / 100:.2f}"
    spent_str = f"{spend_cents / 100:.2f}"

    if ratio >= 1.0:
        await _send_threshold_notification(
            tenant_id, "payg_100", period_start,
            budget=budget_str, spent=spent_str,
        )
    elif ratio >= 0.80:
        await _send_threshold_notification(
            tenant_id, "payg_80", period_start,
            budget=budget_str, spent=spent_str,
        )
