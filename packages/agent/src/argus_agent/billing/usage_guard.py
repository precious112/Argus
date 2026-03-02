"""FastAPI dependencies that enforce plan limits in SaaS mode."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import func, select

from argus_agent.billing.plans import get_plan_limits
from argus_agent.config import get_settings
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import ApiKey, TeamMember, Tenant

logger = logging.getLogger("argus.billing.guard")


def _is_saas() -> bool:
    return get_settings().deployment.mode == "saas"


async def _get_tenant_plan(tenant_id: str) -> str:
    """Look up the tenant's current plan."""
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        return tenant.plan if tenant else "free"


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


async def check_event_ingest_limit(tenant_id: str) -> None:
    """Raise 429 if the tenant has exceeded their monthly event limit."""
    if not _is_saas():
        return

    plan = await _get_tenant_plan(tenant_id)
    limits = get_plan_limits(plan)

    try:
        from argus_agent.storage.repositories import get_metrics_repository

        repo = get_metrics_repository()
        # Count events this calendar month
        now = datetime.now(UTC).replace(tzinfo=None)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        count = await repo.count_events_since(tenant_id, start_of_month)
    except Exception:
        logger.debug("Could not check event count, allowing ingest", exc_info=True)
        return

    if count >= limits.monthly_event_limit:
        raise HTTPException(
            429,
            f"Monthly event limit reached ({count:,}/{limits.monthly_event_limit:,}). "
            "Upgrade your plan for higher limits.",
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
    plan = await _get_tenant_plan(tenant_id)
    limits = get_plan_limits(plan)

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
        now = datetime.now(UTC).replace(tzinfo=None)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        events_count = await repo.count_events_since(tenant_id, start_of_month)
    except Exception:
        pass

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
        "features": {
            "webhook_enabled": limits.webhook_enabled,
            "custom_dashboards": limits.custom_dashboards,
            "external_alert_channels": limits.external_alert_channels,
            "audit_log": limits.audit_log,
            "on_call_rotation": limits.on_call_rotation,
            "service_ownership": limits.service_ownership,
        },
    }
