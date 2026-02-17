"""Dependency analysis and mapping tools."""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk, resolve_time_range

logger = logging.getLogger("argus.tools.dependencies")


class DependencyAnalysisTool(Tool):
    """Aggregate dependency call statistics."""

    @property
    def name(self) -> str:
        return "query_dependency_analysis"

    @property
    def description(self) -> str:
        return (
            "Analyze outgoing dependency calls (HTTP, database, etc.) from your services. "
            "Shows call count, avg/p50/p95 duration, and error rate per dependency type "
            "and target. Use this to find slow or failing external calls."
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
                    "description": "Filter by calling service name",
                },
                "dep_type": {
                    "type": "string",
                    "description": "Filter by dependency type (http, db, etc.)",
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
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        since_dt, until_dt = resolve_time_range(
            kwargs.get("since_minutes", 60), kwargs.get("since"), kwargs.get("until"),
        )
        try:
            from argus_agent.storage.timeseries import query_dependency_summary

            summary = query_dependency_summary(
                service=kwargs.get("service", ""),
                since_minutes=kwargs.get("since_minutes", 60),
                since_dt=since_dt,
                until_dt=until_dt,
            )
        except RuntimeError:
            return {"error": "Time-series store not initialized", "dependencies": []}

        return {
            "dependencies": summary,
            "count": len(summary),
            "display_type": "table",
        }


class DependencyMapTool(Tool):
    """Build a service-to-dependency edge map."""

    @property
    def name(self) -> str:
        return "query_dependency_map"

    @property
    def description(self) -> str:
        return (
            "Build a dependency graph showing which services call which external "
            "dependencies. Returns edges with call counts. Use this to understand "
            "service topology and identify critical dependencies."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
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
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        since_dt, until_dt = resolve_time_range(
            kwargs.get("since_minutes", 60), kwargs.get("since"), kwargs.get("until"),
        )
        try:
            from argus_agent.storage.timeseries import query_dependency_map

            edges = query_dependency_map(
                since_minutes=kwargs.get("since_minutes", 60),
                since_dt=since_dt,
                until_dt=until_dt,
            )
        except RuntimeError:
            return {"error": "Time-series store not initialized", "edges": []}

        return {
            "edges": edges,
            "count": len(edges),
            "display_type": "graph",
        }


def register_dependency_tools() -> None:
    """Register dependency analysis tools."""
    from argus_agent.tools.base import register_tool

    register_tool(DependencyAnalysisTool())
    register_tool(DependencyMapTool())
