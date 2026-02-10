"""AI token budget management."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from argus_agent.config import AIBudgetConfig

logger = logging.getLogger("argus.scheduler.budget")


@dataclass
class _Window:
    """A time-based counter window."""

    tokens: int = 0
    reset_hour: int = -1
    reset_day: int = -1


class TokenBudget:
    """Tracks token usage against hourly and daily limits.

    Normal-priority tasks are capped at (1 - priority_reserve) of the limit.
    Urgent-priority tasks can use the full limit.
    User chat is never budget-limited.
    """

    def __init__(self, config: AIBudgetConfig | None = None) -> None:
        cfg = config or AIBudgetConfig()
        self._daily_limit = cfg.daily_token_limit
        self._hourly_limit = cfg.hourly_token_limit
        self._priority_reserve = cfg.priority_reserve  # fraction reserved for urgent
        self._hourly = _Window()
        self._daily = _Window()
        self._total_tokens = 0
        self._total_requests = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def can_spend(self, estimated_tokens: int, priority: str = "normal") -> bool:
        """Check whether *estimated_tokens* fit within the budget.

        Args:
            estimated_tokens: tokens the upcoming call is expected to use.
            priority: ``"normal"`` or ``"urgent"``.  Normal tasks are capped
                at ``(1 - priority_reserve)`` of the limit; urgent gets the
                full limit.

        Returns:
            ``True`` if the spend is within budget.
        """
        now = datetime.now(UTC)
        self._maybe_reset(now)

        if priority == "urgent":
            hourly_cap = self._hourly_limit
            daily_cap = self._daily_limit
        else:
            hourly_cap = int(self._hourly_limit * (1 - self._priority_reserve))
            daily_cap = int(self._daily_limit * (1 - self._priority_reserve))

        if self._hourly.tokens + estimated_tokens > hourly_cap:
            return False
        if self._daily.tokens + estimated_tokens > daily_cap:
            return False
        return True

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        source: str = "",
    ) -> None:
        """Record actual token consumption after an LLM call."""
        now = datetime.now(UTC)
        self._maybe_reset(now)

        total = prompt_tokens + completion_tokens
        self._hourly.tokens += total
        self._daily.tokens += total
        self._total_tokens += total
        self._total_requests += 1

        logger.debug(
            "Token usage recorded: %d tokens (source=%s, hourly=%d/%d, daily=%d/%d)",
            total,
            source,
            self._hourly.tokens,
            self._hourly_limit,
            self._daily.tokens,
            self._daily_limit,
        )

    def get_status(self) -> dict[str, Any]:
        """Return current budget status for UI display."""
        now = datetime.now(UTC)
        self._maybe_reset(now)

        return {
            "hourly_used": self._hourly.tokens,
            "hourly_limit": self._hourly_limit,
            "hourly_pct": round(self._hourly.tokens / self._hourly_limit * 100, 1)
            if self._hourly_limit
            else 0,
            "daily_used": self._daily.tokens,
            "daily_limit": self._daily_limit,
            "daily_pct": round(self._daily.tokens / self._daily_limit * 100, 1)
            if self._daily_limit
            else 0,
            "total_tokens": self._total_tokens,
            "total_requests": self._total_requests,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_reset(self, now: datetime) -> None:
        """Reset hourly/daily windows when the clock rolls over."""
        if now.hour != self._hourly.reset_hour:
            self._hourly.tokens = 0
            self._hourly.reset_hour = now.hour

        if now.day != self._daily.reset_day:
            self._daily.tokens = 0
            self._daily.reset_day = now.day
