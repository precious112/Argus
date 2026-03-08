"""Query and analyze errors/exceptions from SDK telemetry."""

from __future__ import annotations

import json
import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk, resolve_time_range

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
                    "description": "Max error groups to return (default 20)",
                    "default": 20,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service", "")
        since_minutes = kwargs.get("since_minutes", 1440)
        limit = min(kwargs.get("limit", 20), 100)
        since_dt, until_dt = resolve_time_range(
            since_minutes, kwargs.get("since"), kwargs.get("until"),
        )

        try:
            from argus_agent.storage.repositories import get_metrics_repository

            repo = get_metrics_repository()
            groups = repo.query_error_groups(
                service=service,
                since_minutes=since_minutes,
                limit=limit,
                since_dt=since_dt,
                until_dt=until_dt,
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


class ErrorCorrelationTool(Tool):
    """Correlate errors with traces, dependencies, and deploys."""

    @property
    def name(self) -> str:
        return "query_error_correlation"

    @property
    def description(self) -> str:
        return (
            "Correlate an error/exception with related traces, dependency failures, "
            "metric anomalies, and recent deploys. Given an error type or service, "
            "finds the full context around errors to help diagnose root cause."
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
                    "description": "Service to investigate",
                },
                "error_type": {
                    "type": "string",
                    "description": "Error type to correlate (e.g. ValueError, TimeoutError)",
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
        service = kwargs.get("service", "")
        error_type = kwargs.get("error_type", "")
        since_minutes = kwargs.get("since_minutes", 60)

        try:
            from argus_agent.storage.repositories import get_metrics_repository

            repo = get_metrics_repository()
        except RuntimeError:
            return {"error": "Time-series store not initialized"}

        since_dt, until_dt = resolve_time_range(
            since_minutes, kwargs.get("since"), kwargs.get("until"),
        )

        # 1. Find recent errors matching criteria
        conditions = ["timestamp >= ?", "event_type = 'exception'"]
        params: list[Any] = [since_dt]
        if until_dt:
            conditions.append("timestamp <= ?")
            params.append(until_dt)
        if service:
            conditions.append("service = ?")
            params.append(service)
        if error_type:
            conditions.append("json_extract_string(data, '$.type') = ?")
            params.append(error_type)

        where = " AND ".join(conditions)
        errors = repo.execute_raw(
            f"SELECT timestamp, service, data FROM sdk_events "  # noqa: S608
            f"WHERE {where} ORDER BY timestamp DESC LIMIT 10",
            params,
        )

        error_list = []
        trace_ids: set[str] = set()
        for row in errors:
            data = json.loads(row[2]) if isinstance(row[2], str) else row[2]
            err_entry = {
                "timestamp": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "service": row[1],
                "type": data.get("type", ""),
                "message": data.get("message", "")[:200],
                "has_breadcrumbs": "breadcrumbs" in data,
                "breadcrumb_count": len(data.get("breadcrumbs", [])),
            }
            tid = data.get("trace_id")
            if tid:
                err_entry["trace_id"] = tid
                trace_ids.add(tid)
            error_list.append(err_entry)

        # 2. Find related traces
        related_traces = []
        for tid in list(trace_ids)[:5]:
            trace_spans = repo.execute_raw(
                "SELECT name, kind, duration_ms, status, error_type "
                "FROM spans WHERE trace_id = ? ORDER BY timestamp LIMIT 10",
                [tid],
            )
            related_traces.append({
                "trace_id": tid,
                "span_count": len(trace_spans),
                "spans": [
                    {"name": s[0], "kind": s[1], "duration_ms": s[2],
                     "status": s[3], "error_type": s[4]}
                    for s in trace_spans
                ],
            })

        # 3. Find dependency failures around the same time
        dep_conditions = ["timestamp >= ?", "status != 'ok'"]
        dep_params: list[Any] = [since_dt]
        if until_dt:
            dep_conditions.append("timestamp <= ?")
            dep_params.append(until_dt)
        if service:
            dep_conditions.append("service = ?")
            dep_params.append(service)
        dep_where = " AND ".join(dep_conditions)

        dep_failures = repo.execute_raw(
            f"SELECT dep_type, target, operation, error_message, "  # noqa: S608
            f"COUNT(*) AS cnt "
            f"FROM dependency_calls WHERE {dep_where} "
            f"GROUP BY dep_type, target, operation, error_message "
            f"ORDER BY cnt DESC LIMIT 10",
            dep_params,
        )

        dep_list = [
            {"dep_type": r[0], "target": r[1], "operation": r[2],
             "error_message": r[3], "count": r[4]}
            for r in dep_failures
        ]

        # 4. Find recent deploys
        deploy_conditions = ["timestamp >= ?"]
        deploy_params: list[Any] = [since_dt]
        if until_dt:
            deploy_conditions.append("timestamp <= ?")
            deploy_params.append(until_dt)
        if service:
            deploy_conditions.append("service = ?")
            deploy_params.append(service)
        deploy_where = " AND ".join(deploy_conditions)

        deploys = repo.execute_raw(
            f"SELECT timestamp, service, version, git_sha "  # noqa: S608
            f"FROM deploy_events WHERE {deploy_where} "
            f"ORDER BY timestamp DESC LIMIT 5",
            deploy_params,
        )

        deploy_list = [
            {"timestamp": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
             "service": r[1], "version": r[2], "git_sha": r[3]}
            for r in deploys
        ]

        return {
            "errors": error_list,
            "related_traces": related_traces,
            "dependency_failures": dep_list,
            "recent_deploys": deploy_list,
            "display_type": "correlation",
        }


def register_error_analysis_tools() -> None:
    """Register error analysis tools."""
    from argus_agent.tools.base import register_tool

    register_tool(ErrorAnalysisTool())
    register_tool(ErrorCorrelationTool())
