"""Canonical plan definitions, pricing, and limit lookups."""

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
    "business": PlanLimits(
        name="Business",
        monthly_event_limit=300_000,
        max_team_members=30,
        max_api_keys=30,
        max_services=30,
        data_retention_days=90,
        conversation_retention_days=270,
        daily_ai_messages=-1,
        webhook_enabled=True,
        custom_dashboards=True,
        external_alert_channels=True,
        audit_log=True,
        on_call_rotation=True,
        service_ownership=True,
    ),
}

# Plan pricing (monthly and annual in cents)
PLAN_PRICING: dict[str, dict[str, int]] = {
    "teams": {"monthly_cents": 2500, "annual_cents": 24000},    # $25/mo | $240/yr
    "business": {"monthly_cents": 6000, "annual_cents": 57600},  # $60/mo | $576/yr
}

# PAYG rate: $0.0003/event = 0.03 cents/event = $0.30 per 1K events
PAYG_RATE_CENTS_PER_EVENT = 0.03

# Notification thresholds
QUOTA_WARNING_THRESHOLDS = [0.80, 1.00]
PAYG_WARNING_THRESHOLDS = [0.80, 1.00]


def get_plan_limits(plan: str) -> PlanLimits:
    """Return limits for *plan*, defaulting to free."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
