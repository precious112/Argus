"""Query and analyze errors/exceptions from SDK telemetry."""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.error_analysis")


class ErrorAnalysisTool(Tool):
    """Group and analyze errors/exceptions from SDK telemetry."""

    @property
    def name(self) -> str:
        return "query_error_analysis"

    @property
    def description(self) -> str:
        return (
            "Analyze errors and exceptions from SDK-instrumented applications. "
            "Groups similar errors by type and message, showing occurrence count, "
            "first/last seen timestamps. Use this to find the most frequent "
            "errors and debug patterns."
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
                "since_minutes": {
                    "type": "integer",
                    "description": "Look back N minutes (default 1440 = 24h)",
                    "default": 1440,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max error groups to return (default 20)",
                    "default": 20,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service", "")
        since_minutes = kwargs.get("since_minutes", 1440)
        limit = min(kwargs.get("limit", 20), 100)

        try:
            from argus_agent.storage.timeseries import query_error_groups

            groups = query_error_groups(
                service=service,
                since_minutes=since_minutes,
                limit=limit,
            )
        except RuntimeError:
            return {"error": "Time-series store not initialized", "error_groups": []}

        total_errors = sum(g["count"] for g in groups)

        return {
            "error_groups": groups,
            "total_unique_errors": len(groups),
            "total_error_count": total_errors,
            "since_minutes": since_minutes,
            "display_type": "table",
        }


def register_error_analysis_tools() -> None:
    """Register error analysis tools."""
    from argus_agent.tools.base import register_tool

    register_tool(ErrorAnalysisTool())
