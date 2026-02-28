"""Token usage tracking and analytics service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from argus_agent.storage.models import TokenUsage
from argus_agent.storage.repositories import get_session

logger = logging.getLogger("argus.storage.token_usage")

# Approximate cost per 1K tokens (input, output) for known models.
# Rates derived from official per-MTok pricing ÷ 1000.
# Fallback: use _default for unknown models; prefix matching handles variants.
_COST_PER_1K: dict[str, tuple[float, float]] = {
    # OpenAI — https://developers.openai.com/api/docs/pricing
    "gpt-4o": (0.0025, 0.01),            # $2.50/$10 per MTok
    "gpt-4o-mini": (0.00015, 0.0006),     # $0.15/$0.60 per MTok
    "gpt-4.1": (0.002, 0.008),            # $2/$8 per MTok
    "gpt-4.1-mini": (0.0004, 0.0016),     # $0.40/$1.60 per MTok
    "gpt-4-turbo": (0.01, 0.03),          # $10/$30 per MTok (legacy)
    "gpt-4": (0.03, 0.06),                # $30/$60 per MTok (legacy)
    "gpt-3.5-turbo": (0.0005, 0.0015),    # $0.50/$1.50 per MTok (legacy)
    "gpt-5": (0.00125, 0.01),             # $1.25/$10 per MTok
    "gpt-5.1": (0.00125, 0.01),           # $1.25/$10 per MTok
    "gpt-5.2": (0.00175, 0.014),          # $1.75/$14 per MTok
    "gpt-5-mini": (0.00025, 0.002),       # $0.25/$2 per MTok
    "gpt-5-nano": (0.00005, 0.0004),      # $0.05/$0.40 per MTok
    "o1": (0.015, 0.06),                  # $15/$60 per MTok
    "o3": (0.002, 0.008),                 # $2/$8 per MTok
    "o4-mini": (0.0011, 0.0044),          # $1.10/$4.40 per MTok
    # Anthropic — https://platform.claude.com/docs/en/about-claude/pricing
    "claude-opus-4-6-20260204": (0.005, 0.025),    # $5/$25 per MTok
    "claude-opus-4-5-20250520": (0.005, 0.025),    # $5/$25 per MTok
    "claude-sonnet-4-5-20250929": (0.003, 0.015),  # $3/$15 per MTok
    "claude-sonnet-4-20250514": (0.003, 0.015),    # $3/$15 per MTok
    "claude-haiku-4-5-20251001": (0.001, 0.005),   # $1/$5 per MTok
    "claude-3-5-sonnet-20241022": (0.003, 0.015),  # $3/$15 per MTok (legacy)
    "claude-3-haiku-20240307": (0.00025, 0.00125), # $0.25/$1.25 per MTok (legacy)
    "claude-3-opus-20240229": (0.015, 0.075),      # $15/$75 per MTok (legacy)
    # Google Gemini — https://ai.google.dev/gemini-api/docs/pricing
    "gemini-2.5-pro": (0.00125, 0.01),    # $1.25/$10 per MTok (≤200k input)
    "gemini-2.5-flash": (0.0003, 0.0025), # $0.30/$2.50 per MTok
    "gemini-2.5-flash-lite": (0.0001, 0.0004),  # $0.10/$0.40 per MTok
    "gemini-2.0-flash": (0.0001, 0.0004), # $0.10/$0.40 per MTok
    "gemini-2.0-flash-lite": (0.000075, 0.0003), # $0.075/$0.30 per MTok
    "gemini-1.5-pro": (0.00125, 0.005),   # $1.25/$5 per MTok
    "gemini-1.5-flash": (0.000075, 0.0003), # $0.075/$0.30 per MTok
    # Fallback for unknown models
    "_default": (0.002, 0.008),
}

_STRFTIME_FORMATS: dict[str, str] = {
    "hour": "%Y-%m-%d %H:00",
    "day": "%Y-%m-%d",
    "week": "%Y-%W",
    "month": "%Y-%m",
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = _COST_PER_1K.get(model)
    if rates is None:
        # Try prefix match: longest matching key wins
        best = ""
        for key in _COST_PER_1K:
            if key != "_default" and model.startswith(key) and len(key) > len(best):
                best = key
        rates = _COST_PER_1K[best] if best else _COST_PER_1K["_default"]
    return (prompt_tokens / 1000) * rates[0] + (completion_tokens / 1000) * rates[1]


class TokenUsageService:
    """Persist and query LLM token usage from the database."""

    async def record(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        provider: str,
        model: str,
        source: str = "",
        conversation_id: str = "",
    ) -> int:
        """Insert a token usage row. Returns the row ID."""
        async with get_session() as session:
            entry = TokenUsage(
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                source=source,
                conversation_id=conversation_id,
            )
            session.add(entry)
            await session.flush()
            entry_id = entry.id
            await session.commit()
            return entry_id

    async def get_usage_over_time(
        self,
        granularity: str = "hour",
        since: datetime | None = None,
        provider: str | None = None,
        model: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate token usage by time bucket."""
        fmt = _STRFTIME_FORMATS.get(granularity, _STRFTIME_FORMATS["hour"])
        since = since or datetime.now(UTC) - timedelta(hours=24)

        async with get_session() as session:
            bucket_expr = func.strftime(fmt, TokenUsage.timestamp)
            stmt = (
                select(
                    bucket_expr.label("bucket"),
                    func.sum(TokenUsage.prompt_tokens).label("prompt_tokens"),
                    func.sum(TokenUsage.completion_tokens).label("completion_tokens"),
                    func.sum(
                        TokenUsage.prompt_tokens + TokenUsage.completion_tokens
                    ).label("total_tokens"),
                    func.count().label("request_count"),
                )
                .where(TokenUsage.timestamp >= since)
                .group_by(text("1"))
                .order_by(text("1"))
            )
            if provider:
                stmt = stmt.where(TokenUsage.provider == provider)
            if model:
                stmt = stmt.where(TokenUsage.model == model)
            if source:
                stmt = stmt.where(TokenUsage.source == source)

            result = await session.execute(stmt)
            return [
                {
                    "bucket": row.bucket,
                    "prompt_tokens": row.prompt_tokens or 0,
                    "completion_tokens": row.completion_tokens or 0,
                    "total_tokens": row.total_tokens or 0,
                    "request_count": row.request_count or 0,
                }
                for row in result
            ]

    async def get_usage_by_dimension(
        self,
        dimension: str = "provider",
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Group usage by provider, model, or source."""
        since = since or datetime.now(UTC) - timedelta(hours=24)

        col_map = {
            "provider": TokenUsage.provider,
            "model": TokenUsage.model,
            "source": TokenUsage.source,
        }
        col = col_map.get(dimension, TokenUsage.provider)

        async with get_session() as session:
            stmt = (
                select(
                    col.label("name"),
                    func.sum(TokenUsage.prompt_tokens).label("prompt_tokens"),
                    func.sum(TokenUsage.completion_tokens).label("completion_tokens"),
                    func.sum(
                        TokenUsage.prompt_tokens + TokenUsage.completion_tokens
                    ).label("total_tokens"),
                    func.count().label("request_count"),
                )
                .where(TokenUsage.timestamp >= since)
                .group_by(col)
                .order_by(func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens).desc())
            )
            result = await session.execute(stmt)
            return [
                {
                    "name": row.name or "unknown",
                    "prompt_tokens": row.prompt_tokens or 0,
                    "completion_tokens": row.completion_tokens or 0,
                    "total_tokens": row.total_tokens or 0,
                    "request_count": row.request_count or 0,
                }
                for row in result
            ]

    async def get_summary(self) -> dict[str, Any]:
        """Aggregate stats: totals, today, this week, this month, estimated cost."""
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = today_start.replace(day=1)

        async with get_session() as session:
            # All-time totals
            stmt_all = select(
                func.coalesce(func.sum(TokenUsage.prompt_tokens), 0).label("prompt"),
                func.coalesce(func.sum(TokenUsage.completion_tokens), 0).label("completion"),
                func.coalesce(
                    func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0
                ).label("total"),
                func.count().label("requests"),
            )
            row_all = (await session.execute(stmt_all)).one()

            # Today
            stmt_today = select(
                func.coalesce(
                    func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0
                ).label("total"),
            ).where(TokenUsage.timestamp >= today_start)
            today_tokens = (await session.execute(stmt_today)).scalar() or 0

            # This week
            stmt_week = select(
                func.coalesce(
                    func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0
                ).label("total"),
            ).where(TokenUsage.timestamp >= week_start)
            week_tokens = (await session.execute(stmt_week)).scalar() or 0

            # This month
            stmt_month = select(
                func.coalesce(
                    func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0
                ).label("total"),
            ).where(TokenUsage.timestamp >= month_start)
            month_tokens = (await session.execute(stmt_month)).scalar() or 0

            # Estimated cost — aggregate per model
            stmt_cost = (
                select(
                    TokenUsage.model,
                    func.sum(TokenUsage.prompt_tokens).label("prompt"),
                    func.sum(TokenUsage.completion_tokens).label("completion"),
                )
                .group_by(TokenUsage.model)
            )
            cost_rows = (await session.execute(stmt_cost)).all()
            estimated_cost = sum(
                _estimate_cost(r.model, r.prompt or 0, r.completion or 0)
                for r in cost_rows
            )

        total_requests = row_all.requests or 0
        total_tokens = row_all.total or 0
        return {
            "total_tokens": total_tokens,
            "total_requests": total_requests,
            "prompt_tokens": row_all.prompt or 0,
            "completion_tokens": row_all.completion or 0,
            "avg_tokens_per_request": round(total_tokens / total_requests) if total_requests else 0,
            "estimated_cost_usd": round(estimated_cost, 4),
            "today_tokens": today_tokens,
            "this_week_tokens": week_tokens,
            "this_month_tokens": month_tokens,
        }
