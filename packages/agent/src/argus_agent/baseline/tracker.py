"""System baseline tracker - learns what's normal over time."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from argus_agent.storage.repositories import get_metrics_repository

logger = logging.getLogger("argus.baseline.tracker")


@dataclass
class MetricBaseline:
    """Statistical baseline for a single metric."""

    metric_name: str
    mean: float
    stddev: float
    min: float
    max: float
    p50: float
    p95: float
    p99: float
    sample_count: int


class BaselineTracker:
    """Computes and caches metric baselines from DuckDB aggregate SQL.

    ``update_baselines()`` re-queries the last 7 days of data and stores
    results both in memory and in the ``metric_baselines`` DuckDB table.
    """

    def __init__(self) -> None:
        self._baselines: dict[str, MetricBaseline] = {}

    def get_baseline(self, metric_name: str) -> MetricBaseline | None:
        return self._baselines.get(metric_name)

    def update_baselines(self) -> None:
        """Recompute baselines from the last 7 days of system_metrics data."""
        repo = get_metrics_repository()
        since = datetime.now(UTC) - timedelta(days=7)

        rows = repo.execute_raw(
            """
            SELECT
                metric_name,
                AVG(value)                          AS mean,
                STDDEV_POP(value)                   AS stddev,
                MIN(value)                          AS min_val,
                MAX(value)                          AS max_val,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY value) AS p50,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value) AS p95,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY value) AS p99,
                COUNT(*)                            AS sample_count
            FROM system_metrics
            WHERE timestamp >= ?
            GROUP BY metric_name
            HAVING COUNT(*) >= 10
            """,
            [since],
        )

        updated: dict[str, MetricBaseline] = {}
        for row in rows:
            bl = MetricBaseline(
                metric_name=row[0],
                mean=float(row[1]),
                stddev=float(row[2]) if row[2] is not None else 0.0,
                min=float(row[3]),
                max=float(row[4]),
                p50=float(row[5]),
                p95=float(row[6]),
                p99=float(row[7]),
                sample_count=int(row[8]),
            )
            updated[bl.metric_name] = bl

        self._baselines = updated

        # Persist to metrics store for other consumers
        self._persist(repo, updated)

        logger.info("Baselines updated for %d system metrics", len(updated))

    def update_sdk_baselines(self) -> None:
        """Compute baselines from SDK runtime metrics and span durations."""
        repo = get_metrics_repository()
        since = datetime.now(UTC) - timedelta(days=7)

        updated: dict[str, MetricBaseline] = {}

        # 1. SDK runtime metrics from sdk_metrics table
        sdk_rows = repo.execute_raw(
            """
            SELECT
                'sdk.' || service || '.' || metric_name AS metric_key,
                AVG(value)                          AS mean,
                STDDEV_POP(value)                   AS stddev,
                MIN(value)                          AS min_val,
                MAX(value)                          AS max_val,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY value) AS p50,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value) AS p95,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY value) AS p99,
                COUNT(*)                            AS sample_count
            FROM sdk_metrics
            WHERE timestamp >= ?
            GROUP BY metric_key
            HAVING COUNT(*) >= 10
            """,
            [since],
        )

        for row in sdk_rows:
            bl = MetricBaseline(
                metric_name=row[0],
                mean=float(row[1]),
                stddev=float(row[2]) if row[2] is not None else 0.0,
                min=float(row[3]),
                max=float(row[4]),
                p50=float(row[5]),
                p95=float(row[6]),
                p99=float(row[7]),
                sample_count=int(row[8]),
            )
            updated[bl.metric_name] = bl

        # 2. Span durations grouped by service + name
        span_rows = repo.execute_raw(
            """
            SELECT
                'sdk.' || service || '.span.' || name AS metric_key,
                AVG(duration_ms)                    AS mean,
                STDDEV_POP(duration_ms)             AS stddev,
                MIN(duration_ms)                    AS min_val,
                MAX(duration_ms)                    AS max_val,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99,
                COUNT(*)                            AS sample_count
            FROM spans
            WHERE timestamp >= ? AND duration_ms IS NOT NULL
            GROUP BY metric_key
            HAVING COUNT(*) >= 10
            """,
            [since],
        )

        for row in span_rows:
            bl = MetricBaseline(
                metric_name=row[0],
                mean=float(row[1]),
                stddev=float(row[2]) if row[2] is not None else 0.0,
                min=float(row[3]),
                max=float(row[4]),
                p50=float(row[5]),
                p95=float(row[6]),
                p99=float(row[7]),
                sample_count=int(row[8]),
            )
            updated[bl.metric_name] = bl

        # 3. Traffic request counts per service (5-min buckets over 7 days)
        traffic_rows = repo.execute_raw(
            """
            SELECT
                'traffic.' || service || '.request_count_5m' AS metric_key,
                AVG(cnt)                            AS mean,
                STDDEV_POP(cnt)                     AS stddev,
                MIN(cnt)                            AS min_val,
                MAX(cnt)                            AS max_val,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY cnt) AS p50,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cnt) AS p95,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY cnt) AS p99,
                COUNT(*)                            AS sample_count
            FROM (
                SELECT
                    service,
                    time_bucket(INTERVAL '5 minutes', timestamp) AS bucket,
                    COUNT(*) AS cnt
                FROM spans
                WHERE timestamp >= ? AND kind = 'server'
                GROUP BY service, bucket
            ) sub
            GROUP BY metric_key
            HAVING COUNT(*) >= 10
            """,
            [since],
        )

        for row in traffic_rows:
            bl = MetricBaseline(
                metric_name=row[0],
                mean=float(row[1]),
                stddev=float(row[2]) if row[2] is not None else 0.0,
                min=float(row[3]),
                max=float(row[4]),
                p50=float(row[5]),
                p95=float(row[6]),
                p99=float(row[7]),
                sample_count=int(row[8]),
            )
            updated[bl.metric_name] = bl

        # Merge into existing baselines (don't overwrite system baselines)
        self._baselines.update(updated)

        # Persist all baselines
        self._persist(repo, self._baselines)

        logger.info("SDK baselines updated for %d metrics", len(updated))

    def format_for_prompt(self) -> str:
        """Format current baselines as text for the agent system prompt."""
        if not self._baselines:
            return ""

        lines: list[str] = []
        for bl in sorted(self._baselines.values(), key=lambda b: b.metric_name):
            lines.append(
                f"- {bl.metric_name}: mean={bl.mean:.1f}, "
                f"p50={bl.p50:.1f}, p95={bl.p95:.1f}, p99={bl.p99:.1f} "
                f"(n={bl.sample_count})"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _persist(repo: Any, baselines: dict[str, MetricBaseline]) -> None:
        """Write baselines to the metric_baselines table."""
        now = datetime.now(UTC)
        repo.execute_raw("DELETE FROM metric_baselines")
        for bl in baselines.values():
            repo.execute_raw(
                "INSERT INTO metric_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    now,
                    bl.metric_name,
                    bl.mean,
                    bl.stddev,
                    bl.min,
                    bl.max,
                    bl.p50,
                    bl.p95,
                    bl.p99,
                    bl.sample_count,
                ],
            )
