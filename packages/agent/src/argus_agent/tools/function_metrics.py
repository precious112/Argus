"""Query aggregated serverless function metrics tool."""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk, resolve_time_range

logger = logging.getLogger("argus.tools.function_metrics")


class FunctionMetricsTool(Tool):
    """Query aggregated serverless function performance metrics."""

    @property
    def name(self) -> str:
        return "query_function_metrics"

    @property
    def description(self) -> str:
        return (
            "Query aggregated serverless function metrics from SDK telemetry. "
            "Returns time-bucketed data with invocation count, error rate, "
            "p50/p95/p99 latency, and cold start percentage. "
            "Use this to analyze function performance over time."
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
                    "description": "Filter by service name",
                },
                "function_name": {
                    "type": "string",
                    "description": "Filter by function name",
                },
                "since_minutes": {
                    "type": "integer",
                    "description": "Look back N minutes (default 60)",
                    "default": 60,
                },
                "since": {
                    "type": "string",
                    "description": "ISO datetime lower bound (overrides since_minutes)",
                },
                "until": {
                    "type": "string",
                    "description": "ISO datetime upper bound",
                },
                "interval_minutes": {
                    "type": "integer",
                    "description": "Bucket interval in minutes (default 5)",
                    "default": 5,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service", "")
        function_name = kwargs.get("function_name", "")
        since_minutes = kwargs.get("since_minutes", 60)
        interval_minutes = kwargs.get("interval_minutes", 5)
        since_dt, until_dt = resolve_time_range(
            since_minutes, kwargs.get("since"), kwargs.get("until"),
        )

        try:
            from argus_agent.storage.repositories import get_metrics_repository

            buckets = get_metrics_repository().query_function_metrics(
                service=service,
                function_name=function_name,
                since_minutes=since_minutes,
                interval_minutes=interval_minutes,
                since_dt=since_dt,
                until_dt=until_dt,
            )
        except RuntimeError:
            return {"error": "Time-series store not initialized", "buckets": []}

        # Compute summary stats across all buckets
        total_invocations = sum(b["invocation_count"] for b in buckets)
        total_errors = sum(b["error_count"] for b in buckets)
        total_cold_starts = sum(b["cold_start_count"] for b in buckets)

        return {
            "buckets": buckets,
            "summary": {
                "total_invocations": total_invocations,
                "total_errors": total_errors,
                "overall_error_rate": round(
                    total_errors / total_invocations * 100, 1
                ) if total_invocations > 0 else 0,
                "total_cold_starts": total_cold_starts,
                "bucket_count": len(buckets),
            },
            "since_minutes": since_minutes,
            "interval_minutes": interval_minutes,
            "display_type": "metrics_chart",
        }


def register_function_metrics_tools() -> None:
    """Register function metrics tools."""
    from argus_agent.tools.base import register_tool

    register_tool(FunctionMetricsTool())
