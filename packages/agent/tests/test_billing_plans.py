"""Tests for billing plan limits and pricing."""

from __future__ import annotations

from argus_agent.billing.plans import (
    PAYG_RATE_CENTS_PER_EVENT,
    PLAN_LIMITS,
    PLAN_PRICING,
    get_plan_limits,
)


def test_free_plan_limits():
    limits = get_plan_limits("free")
    assert limits.name == "Free"
    assert limits.monthly_event_limit == 5_000
    assert limits.max_team_members == 1
    assert limits.max_api_keys == 1
    assert limits.max_services == 1
    assert limits.data_retention_days == 3
    assert limits.conversation_retention_days == 3
    assert limits.daily_ai_messages == 10
    assert limits.webhook_enabled is False
    assert limits.custom_dashboards is False
    assert limits.external_alert_channels is False
    assert limits.audit_log is False
    assert limits.on_call_rotation is False
    assert limits.service_ownership is False


def test_teams_plan_limits():
    limits = get_plan_limits("teams")
    assert limits.name == "Teams"
    assert limits.monthly_event_limit == 100_000
    assert limits.max_team_members == 10
    assert limits.max_api_keys == 10
    assert limits.max_services == 10
    assert limits.data_retention_days == 30
    assert limits.conversation_retention_days == 90
    assert limits.daily_ai_messages == -1  # unlimited
    assert limits.webhook_enabled is True
    assert limits.custom_dashboards is True
    assert limits.external_alert_channels is True
    assert limits.audit_log is True
    assert limits.on_call_rotation is True
    assert limits.service_ownership is True


def test_business_plan_limits():
    limits = get_plan_limits("business")
    assert limits.name == "Business"
    assert limits.monthly_event_limit == 300_000
    assert limits.max_team_members == 30
    assert limits.max_api_keys == 30
    assert limits.max_services == 30
    assert limits.data_retention_days == 90
    assert limits.conversation_retention_days == 270
    assert limits.daily_ai_messages == -1  # unlimited
    assert limits.webhook_enabled is True


def test_business_is_3x_teams():
    """Business plan limits should be 3x Teams for numeric quotas."""
    teams = get_plan_limits("teams")
    biz = get_plan_limits("business")
    assert biz.monthly_event_limit == teams.monthly_event_limit * 3
    assert biz.max_team_members == teams.max_team_members * 3
    assert biz.max_api_keys == teams.max_api_keys * 3
    assert biz.max_services == teams.max_services * 3
    assert biz.data_retention_days == teams.data_retention_days * 3
    assert biz.conversation_retention_days == teams.conversation_retention_days * 3


def test_unknown_plan_falls_back_to_free():
    limits = get_plan_limits("nonexistent")
    assert limits.name == "Free"
    assert limits.monthly_event_limit == 5_000


def test_plan_limits_frozen():
    limits = get_plan_limits("free")
    try:
        limits.monthly_event_limit = 999  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass


def test_plan_limits_dict_has_expected_keys():
    assert "free" in PLAN_LIMITS
    assert "teams" in PLAN_LIMITS
    assert "business" in PLAN_LIMITS


def test_plan_pricing_has_teams_and_business():
    assert "teams" in PLAN_PRICING
    assert "business" in PLAN_PRICING
    assert PLAN_PRICING["teams"]["monthly_cents"] == 2500
    assert PLAN_PRICING["teams"]["annual_cents"] == 24000
    assert PLAN_PRICING["business"]["monthly_cents"] == 6000
    assert PLAN_PRICING["business"]["annual_cents"] == 57600


def test_annual_discount_is_20_percent():
    """Annual pricing should be ~80% of 12x monthly."""
    for plan_id, prices in PLAN_PRICING.items():
        full_annual = prices["monthly_cents"] * 12
        actual_annual = prices["annual_cents"]
        discount = 1 - (actual_annual / full_annual)
        assert abs(discount - 0.20) < 0.01, (
            f"{plan_id} annual discount is {discount:.1%}, expected 20%"
        )


def test_payg_rate():
    """PAYG rate should be $0.30 per 1K events = 0.03 cents/event."""
    assert PAYG_RATE_CENTS_PER_EVENT == 0.03
    # $0.30 per 1000 events
    assert PAYG_RATE_CENTS_PER_EVENT * 1000 == 30  # 30 cents = $0.30
