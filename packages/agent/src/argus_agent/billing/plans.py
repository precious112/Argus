"""Canonical plan definitions and limit lookups."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanLimits:
    name: str
    monthly_event_limit: int
    max_team_members: int
    max_api_keys: int
    max_services: int
    data_retention_days: int
    conversation_retention_days: int
    daily_ai_messages: int  # -1 = unlimited
    webhook_enabled: bool
    custom_dashboards: bool
    external_alert_channels: bool
    audit_log: bool
    on_call_rotation: bool
    service_ownership: bool


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        name="Free",
        monthly_event_limit=5_000,
        max_team_members=1,
        max_api_keys=1,
        max_services=1,
        data_retention_days=3,
        conversation_retention_days=3,
        daily_ai_messages=10,
        webhook_enabled=False,
        custom_dashboards=False,
        external_alert_channels=False,
        audit_log=False,
        on_call_rotation=False,
        service_ownership=False,
    ),
    "teams": PlanLimits(
        name="Teams",
        monthly_event_limit=100_000,
        max_team_members=10,
        max_api_keys=10,
        max_services=10,
        data_retention_days=30,
        conversation_retention_days=90,
        daily_ai_messages=-1,
        webhook_enabled=True,
        custom_dashboards=True,
        external_alert_channels=True,
        audit_log=True,
        on_call_rotation=True,
        service_ownership=True,
    ),
}

# Usage-based scaling tiers for Teams plan: (event_ceiling, price_dollars)
USAGE_TIERS: list[tuple[int, int]] = [
    (100_000, 25),       # base: $25/mo
    (500_000, 50),       # 100K–500K: $50/mo
    (2_000_000, 100),    # 500K–2M: $100/mo
    (10_000_000, 250),   # 2M–10M: $250/mo
    (50_000_000, 500),   # 10M–50M: $500/mo
]


def get_plan_limits(plan: str) -> PlanLimits:
    """Return limits for *plan*, defaulting to free."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def get_effective_event_limit(plan: str, usage_tier_price: int) -> int:
    """Return the event ceiling for the current usage tier (Teams only)."""
    if plan != "teams":
        return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).monthly_event_limit
    for limit, price in USAGE_TIERS:
        if usage_tier_price <= price:
            return limit
    return 50_000_000  # enterprise-contact tier
