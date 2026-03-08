"""Behavior analysis tool - queries baselines and recent anomalies."""

from __future__ import annotations

import json
import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk, resolve_time_range

logger = logging.getLogger("argus.tools.behavior")


class BehaviorAnalysisTool(Tool):
    """Analyze current behavior vs established baselines."""

    @property
    def name(self) -> str:
        return "query_behavior_analysis"

    @property
    def description(self) -> str:
        return (
            "Analyze current application behavior against established baselines. "
            "Shows which metrics are normal vs anomalous, correlates shifts with "
            "recent deploys and dependency changes. Use this to understand if "
            "anything is abnormal right now."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service to analyze (optional, analyzes all if omitted)",
                },
                "since_minutes": {
                    "type": "integer",
                    "description": "Look back N minutes for recent data (default 30)",
                    "default": 30,
                },
                "since": {
                    "type": "string",
                    "description": "ISO datetime lower bound (overrides since_minutes)",
                },
                "until": {
                    "type": "string",
                    "description": "ISO datetime upper bound",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service", "")
        since_minutes = kwargs.get("since_minutes", 30)

        try:
            from argus_agent.storage.repositories import get_metrics_repository

            repo = get_metrics_repository()
        except RuntimeError:
            return {"error": "Time-series store not initialized"}

        since_dt, until_dt = resolve_time_range(
            since_minutes, kwargs.get("since"), kwargs.get("until"),
        )

        # 1. Get current baselines
        baselines = repo.execute_raw(
            "SELECT metric_name, mean, stddev, p50, p95, p99, sample_count "
            "FROM metric_baselines WHERE metric_name LIKE 'sdk.%'"
        )

        baseline_info = [
            {
                "metric": row[0],
                "mean": round(row[1], 2),
                "stddev": round(row[2], 2),
                "p50": round(row[3], 2),
                "p95": round(row[4], 2),
                "p99": round(row[5], 2),
                "samples": row[6],
            }
            for row in baselines
        ]

        # Filter by service if specified
        if service:
            prefix = f"sdk.{service}."
            baseline_info = [b for b in baseline_info if b["metric"].startswith(prefix)]

        # 2. Query recent SDK runtime metrics
        rt_conditions = ["timestamp >= ?", "event_type = 'runtime_metric'"]
        rt_params: list[Any] = [since_dt]
        if until_dt:
            rt_conditions.append("timestamp <= ?")
            rt_params.append(until_dt)
        rt_where = " AND ".join(rt_conditions)
        anomalies = repo.execute_raw(
            f"SELECT timestamp, service, data FROM sdk_events "  # noqa: S608
            f"WHERE {rt_where} "
            f"ORDER BY timestamp DESC LIMIT 50",
            rt_params,
        )

        # Check each against baselines for anomalies
        anomalous_metrics: list[dict[str, Any]] = []
        baseline_map = {b["metric"]: b for b in baseline_info}

        for row in anomalies:
            data = json.loads(row[2]) if isinstance(row[2], str) else row[2]
            svc = row[1]
            metric_name = data.get("metric_name", "")
            value = data.get("value", 0)

            key = f"sdk.{svc}.{metric_name}"
            bl = baseline_map.get(key)
            if bl and bl["stddev"] > 0:
                z = abs(value - bl["mean"]) / bl["stddev"]
                if z > 2.0:
                    anomalous_metrics.append({
                        "metric": key,
                        "value": round(value, 2),
                        "z_score": round(z, 2),
                        "baseline_mean": bl["mean"],
                        "baseline_stddev": bl["stddev"],
                    })

        # 3. Recent deploys
        deploy_conditions = ["timestamp >= ?"]
        deploy_params: list[Any] = [since_dt]
        if until_dt:
            deploy_conditions.append("timestamp <= ?")
            deploy_params.append(until_dt)
        if service:
            deploy_conditions.append("service = ?")
            deploy_params.append(service)

        deploys = repo.execute_raw(
            f"SELECT timestamp, service, git_sha FROM deploy_events "  # noqa: S608
            f"WHERE {' AND '.join(deploy_conditions)} "
            f"ORDER BY timestamp DESC LIMIT 5",
            deploy_params,
        )

        deploy_list = [
            {
                "timestamp": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "service": r[1],
                "git_sha": r[2],
            }
            for r in deploys
        ]

        # 4. Overall health summary
        health_conditions = ["timestamp >= ?", "duration_ms IS NOT NULL"]
        health_params: list[Any] = [since_dt]
        if until_dt:
            health_conditions.append("timestamp <= ?")
            health_params.append(until_dt)
        if service:
            health_conditions.append("service = ?")
            health_params.append(service)
        health_where = " AND ".join(health_conditions)
        span_health_rows = repo.execute_raw(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE status != 'ok'), "  # noqa: S608
            f"AVG(duration_ms) FROM spans WHERE {health_where}",
            health_params,
        )
        span_health = span_health_rows[0] if span_health_rows else None

        health = {}
        if span_health and span_health[0] > 0:
            health = {
                "total_requests": span_health[0],
                "error_count": span_health[1],
                "error_rate": round(span_health[1] / span_health[0] * 100, 1),
                "avg_duration_ms": round(span_health[2], 2) if span_health[2] else 0,
            }

        return {
            "baselines": baseline_info,
            "anomalous_metrics": anomalous_metrics,
            "recent_deploys": deploy_list,
            "health_summary": health,
            "since_minutes": since_minutes,
            "display_type": "analysis",
        }


def register_behavior_tools() -> None:
    """Register behavior analysis tools."""
    from argus_agent.tools.base import register_tool

    register_tool(BehaviorAnalysisTool())
