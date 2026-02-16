"""Query SDK runtime metrics tool."""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.runtime_metrics")


class RuntimeMetricsTool(Tool):
    """Query application runtime metrics from SDKs."""

    @property
    def name(self) -> str:
        return "query_runtime_metrics"

    @property
    def description(self) -> str:
        return (
            "Query application runtime metrics collected by Argus SDKs. "
            "Includes process memory (RSS, heap), GC stats, thread counts, "
            "and other runtime indicators. Filter by service and metric name."
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
                "metric_name": {
                    "type": "string",
                    "description": (
                        "Filter by metric name (e.g. process_rss_bytes, "
                        "heap_used_bytes, gc_objects_tracked, thread_count)"
                    ),
                },
                "since_minutes": {
                    "type": "integer",
                    "description": "Look back N minutes (default 60)",
                    "default": 60,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max data points to return (default 100)",
                    "default": 100,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            from argus_agent.storage.timeseries import query_sdk_metrics

            metrics = query_sdk_metrics(
                service=kwargs.get("service", ""),
                metric_name=kwargs.get("metric_name", ""),
                since_minutes=kwargs.get("since_minutes", 60),
                limit=min(kwargs.get("limit", 100), 500),
            )
        except RuntimeError:
            return {"error": "Time-series store not initialized", "metrics": []}

        return {
            "metrics": metrics,
            "count": len(metrics),
            "display_type": "table",
        }


def register_runtime_metrics_tools() -> None:
    """Register runtime metrics tools."""
    from argus_agent.tools.base import register_tool

    register_tool(RuntimeMetricsTool())
