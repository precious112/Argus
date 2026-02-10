"""Tests for the token budget system."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from argus_agent.config import AIBudgetConfig
from argus_agent.scheduler.budget import TokenBudget


@pytest.fixture
def budget() -> TokenBudget:
    return TokenBudget(AIBudgetConfig(
        daily_token_limit=100_000,
        hourly_token_limit=20_000,
        priority_reserve=0.3,
    ))


def test_initial_state(budget: TokenBudget):
    status = budget.get_status()
    assert status["hourly_used"] == 0
    assert status["daily_used"] == 0
    assert status["hourly_limit"] == 20_000
    assert status["daily_limit"] == 100_000


def test_can_spend_within_limit(budget: TokenBudget):
    assert budget.can_spend(1000) is True


def test_can_spend_normal_capped_at_70_pct(budget: TokenBudget):
    """Normal priority is capped at (1 - 0.3) = 70% of limits."""
    # 70% of 20_000 = 14_000
    assert budget.can_spend(14_000, priority="normal") is True
    assert budget.can_spend(14_001, priority="normal") is False


def test_can_spend_urgent_uses_full_limit(budget: TokenBudget):
    """Urgent priority can use the full limit."""
    assert budget.can_spend(20_000, priority="urgent") is True
    assert budget.can_spend(20_001, priority="urgent") is False


def test_record_usage_updates_counters(budget: TokenBudget):
    budget.record_usage(500, 300, source="test")
    status = budget.get_status()
    assert status["hourly_used"] == 800
    assert status["daily_used"] == 800
    assert status["total_tokens"] == 800
    assert status["total_requests"] == 1


def test_record_usage_affects_can_spend(budget: TokenBudget):
    budget.record_usage(7000, 7000, source="test")  # 14000 total = 70% of hourly
    # Normal can't spend any more
    assert budget.can_spend(1, priority="normal") is False
    # Urgent still has 6000 headroom
    assert budget.can_spend(6000, priority="urgent") is True
    assert budget.can_spend(6001, priority="urgent") is False


def test_hourly_window_reset(budget: TokenBudget):
    """Hourly counter resets when the hour changes."""
    hour_10 = datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC)
    hour_11 = datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC)

    with patch("argus_agent.scheduler.budget.datetime") as mock_dt:
        mock_dt.now.return_value = hour_10
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        budget.record_usage(10_000, 0, source="test")
        assert budget.get_status()["hourly_used"] == 10_000

        # Advance to next hour
        mock_dt.now.return_value = hour_11
        status = budget.get_status()
        assert status["hourly_used"] == 0  # reset
        assert status["daily_used"] == 10_000  # daily persists


def test_daily_window_reset(budget: TokenBudget):
    """Daily counter resets when the day changes."""
    day_1 = datetime(2025, 1, 1, 23, 59, 0, tzinfo=UTC)
    day_2 = datetime(2025, 1, 2, 0, 1, 0, tzinfo=UTC)

    with patch("argus_agent.scheduler.budget.datetime") as mock_dt:
        mock_dt.now.return_value = day_1
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        budget.record_usage(50_000, 0, source="test")
        assert budget.get_status()["daily_used"] == 50_000

        # Advance to next day
        mock_dt.now.return_value = day_2
        status = budget.get_status()
        assert status["daily_used"] == 0  # reset
        assert status["total_tokens"] == 50_000  # total persists


def test_get_status_percentages(budget: TokenBudget):
    budget.record_usage(5000, 5000, source="test")  # 10_000
    status = budget.get_status()
    assert status["hourly_pct"] == 50.0  # 10_000 / 20_000
    assert status["daily_pct"] == 10.0  # 10_000 / 100_000


def test_multiple_usage_records(budget: TokenBudget):
    budget.record_usage(1000, 500, source="a")
    budget.record_usage(2000, 1000, source="b")
    budget.record_usage(500, 500, source="c")
    status = budget.get_status()
    assert status["hourly_used"] == 5500
    assert status["daily_used"] == 5500
    assert status["total_requests"] == 3
