"""Tests for billing plan limits and tier calculations."""

from __future__ import annotations

from argus_agent.billing.plans import (
    PLAN_LIMITS,
    USAGE_TIERS,
    get_effective_event_limit,
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


def test_usage_tiers_ordered():
    """Tiers should be in ascending order of ceiling."""
    ceilings = [ceiling for ceiling, _ in USAGE_TIERS]
    assert ceilings == sorted(ceilings)


def test_usage_tiers_prices_ascending():
    """Prices should increase with event ceilings."""
    prices = [price for _, price in USAGE_TIERS]
    assert prices == sorted(prices)


def test_effective_event_limit_free():
    assert get_effective_event_limit("free", 0) == 5_000
    assert get_effective_event_limit("free", 100) == 5_000


def test_effective_event_limit_teams_base():
    assert get_effective_event_limit("teams", 25) == 100_000


def test_effective_event_limit_teams_tier2():
    assert get_effective_event_limit("teams", 50) == 500_000


def test_effective_event_limit_teams_tier3():
    assert get_effective_event_limit("teams", 100) == 2_000_000


def test_effective_event_limit_teams_tier4():
    assert get_effective_event_limit("teams", 250) == 10_000_000


def test_effective_event_limit_teams_tier5():
    assert get_effective_event_limit("teams", 500) == 50_000_000


def test_effective_event_limit_teams_enterprise():
    """Prices above the highest tier return enterprise ceiling."""
    assert get_effective_event_limit("teams", 9999) == 50_000_000


def test_plan_limits_dict_has_expected_keys():
    assert "free" in PLAN_LIMITS
    assert "teams" in PLAN_LIMITS
