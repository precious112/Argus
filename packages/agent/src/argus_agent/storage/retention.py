"""Plan-based retention policy management for TimescaleDB."""

from __future__ import annotations

import logging

logger = logging.getLogger("argus.storage.retention")

# Default retention intervals by plan tier
PLAN_RETENTION: dict[str, dict[str, str]] = {
    "free": {
        "system_metrics": "7 days",
        "log_index": "7 days",
        "sdk_events": "7 days",
        "spans": "7 days",
        "dependency_calls": "7 days",
        "sdk_metrics": "7 days",
        "deploy_events": "30 days",
    },
    "pro": {
        "system_metrics": "30 days",
        "log_index": "30 days",
        "sdk_events": "30 days",
        "spans": "30 days",
        "dependency_calls": "30 days",
        "sdk_metrics": "30 days",
        "deploy_events": "90 days",
    },
    "enterprise": {
        "system_metrics": "90 days",
        "log_index": "90 days",
        "sdk_events": "90 days",
        "spans": "90 days",
        "dependency_calls": "90 days",
        "sdk_metrics": "90 days",
        "deploy_events": "365 days",
    },
}


async def apply_retention_policy(pool, plan: str = "pro") -> None:  # type: ignore[no-untyped-def]
    """Apply retention policies based on the tenant's plan.

    Args:
        pool: asyncpg connection pool
        plan: one of 'free', 'pro', 'enterprise'
    """
    intervals = PLAN_RETENTION.get(plan, PLAN_RETENTION["pro"])

    async with pool.acquire() as conn:
        for table, interval in intervals.items():
            try:
                await conn.execute(
                    f"SELECT remove_retention_policy('{table}', if_exists => true)"
                )
                await conn.execute(
                    f"SELECT add_retention_policy('{table}', "
                    f"INTERVAL '{interval}', if_not_exists => true)"
                )
            except Exception:
                logger.warning("Failed to set retention for %s", table, exc_info=True)

    logger.info("Retention policies applied for plan '%s'", plan)
