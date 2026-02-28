"""Deploy history and impact analysis tools."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk, resolve_time_range

logger = logging.getLogger("argus.tools.deploys")


class DeployHistoryTool(Tool):
    """List deploy events per service."""

    @property
    def name(self) -> str:
        return "query_deploy_history"

    @property
    def description(self) -> str:
        return (
            "List recent deploys/version changes for your services. "
            "Shows deploy timestamp, version, git SHA, environment, and "
            "previous version. Use this to track what's been deployed."
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
                    "description": "Look back N minutes (default 10080 = 7 days)",
                    "default": 10080,
                },
                "since": {
                    "type": "string",
                    "description": "ISO datetime lower bound (overrides since_minutes)",
                },
                "until": {
                    "type": "string",
                    "description": "ISO datetime upper bound",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20)",
                    "default": 20,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        since_dt, until_dt = resolve_time_range(
            kwargs.get("since_minutes", 10080), kwargs.get("since"), kwargs.get("until"),
        )
        try:
            from argus_agent.storage.repositories import get_metrics_repository

            repo = get_metrics_repository()
            deploys = repo.query_deploy_history(
                service=kwargs.get("service", ""),
                since_minutes=kwargs.get("since_minutes", 10080),
                limit=min(kwargs.get("limit", 20), 50),
                since_dt=since_dt,
                until_dt=until_dt,
            )
        except RuntimeError:
            return {"error": "Time-series store not initialized", "deploys": []}

        return {
            "deploys": deploys,
            "count": len(deploys),
            "display_type": "table",
        }


class DeployImpactTool(Tool):
    """Compare metrics before vs after a deploy."""

    @property
    def name(self) -> str:
        return "query_deploy_impact"

    @property
    def description(self) -> str:
        return (
            "Analyze the impact of a deploy by comparing error rates, "
            "request latency, and dependency health in a window before "
            "vs after the deploy timestamp. Helps determine if a deploy "
            "caused a regression."
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
                    "description": "Service name to analyze",
                },
                "deploy_timestamp": {
                    "type": "string",
                    "description": "ISO timestamp of the deploy to analyze",
                },
                "window_minutes": {
                    "type": "integer",
                    "description": "Minutes before/after deploy to compare (default 30)",
                    "default": 30,
                },
            },
            "required": ["service"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service", "")
        window = kwargs.get("window_minutes", 30)

        try:
            from argus_agent.storage.repositories import get_metrics_repository

            repo = get_metrics_repository()
        except RuntimeError:
            return {"error": "Time-series store not initialized"}

        # Find the deploy timestamp
        deploy_ts_str = kwargs.get("deploy_timestamp", "")
        if deploy_ts_str:
            deploy_ts = datetime.fromisoformat(deploy_ts_str)
        else:
            # Use most recent deploy for this service
            deploys = repo.query_deploy_history(service=service, limit=1)
            if not deploys:
                return {"error": f"No deploys found for service '{service}'"}
            deploy_ts = datetime.fromisoformat(deploys[0]["timestamp"])

        before_start = deploy_ts - timedelta(minutes=window)
        after_end = deploy_ts + timedelta(minutes=window)

        # Compare span metrics before vs after
        comparison = {}
        for label, start, end in [
            ("before", before_start, deploy_ts),
            ("after", deploy_ts, after_end),
        ]:
            rows = repo.execute_raw(
                "SELECT COUNT(*), "
                "COUNT(*) FILTER (WHERE status != 'ok'), "
                "AVG(duration_ms), "
                "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) "
                "FROM spans WHERE service = ? AND timestamp >= ? AND timestamp < ? "
                "AND duration_ms IS NOT NULL",
                [service, start, end],
            )
            result = rows[0] if rows else None

            total = result[0] if result else 0
            errors = result[1] if result else 0
            comparison[label] = {
                "request_count": total,
                "error_count": errors,
                "error_rate": round(errors / total * 100, 1) if total > 0 else 0,
                "avg_duration_ms": round(result[2], 2) if result and result[2] else 0,
                "p95_duration_ms": round(result[3], 2) if result and result[3] else 0,
            }

        return {
            "service": service,
            "deploy_timestamp": deploy_ts.isoformat(),
            "window_minutes": window,
            "before": comparison["before"],
            "after": comparison["after"],
            "display_type": "comparison",
        }


def register_deploy_tools() -> None:
    """Register deploy analysis tools."""
    from argus_agent.tools.base import register_tool

    register_tool(DeployHistoryTool())
    register_tool(DeployImpactTool())
