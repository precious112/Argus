"""Trace timeline and slow trace analysis tools."""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk, resolve_time_range

logger = logging.getLogger("argus.tools.traces")


class TraceTimelineTool(Tool):
    """Reconstruct a full trace from a trace_id."""

    @property
    def name(self) -> str:
        return "query_trace_timeline"

    @property
    def description(self) -> str:
        return (
            "Reconstruct the full timeline for a distributed trace. "
            "Given a trace_id, returns all spans with parent/child "
            "relationships, durations, and error status. Use this to "
            "understand what happened during a specific request."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "The trace ID to look up",
                },
            },
            "required": ["trace_id"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        trace_id = kwargs.get("trace_id", "")
        if not trace_id:
            return {"error": "trace_id is required", "spans": []}

        limit = 200
        try:
            from argus_agent.storage.repositories import get_metrics_repository

            spans = get_metrics_repository().query_trace(trace_id, limit=limit)
        except RuntimeError:
            return {"error": "Time-series store not initialized", "spans": []}

        # Build span tree
        by_id: dict[str, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []
        for span in spans:
            span["children"] = []
            by_id[span["span_id"]] = span

        for span in spans:
            parent = span.get("parent_span_id")
            if parent and parent in by_id:
                by_id[parent]["children"].append(span["span_id"])
            else:
                roots.append(span)

        result: dict[str, Any] = {
            "trace_id": trace_id,
            "spans": spans,
            "root_spans": [r["span_id"] for r in roots],
            "total_spans": len(spans),
            "display_type": "trace",
        }
        if len(spans) == limit:
            result["truncated"] = True
        return result


class SlowTraceAnalysisTool(Tool):
    """Find the slowest spans by service/name."""

    @property
    def name(self) -> str:
        return "query_slow_traces"

    @property
    def description(self) -> str:
        return (
            "Find the slowest spans/traces with p50/p95/p99 duration breakdowns. "
            "Shows which endpoints or functions are taking the longest. "
            "Optionally filter by service name."
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
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20)",
                    "default": 20,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service", "")
        since_minutes = kwargs.get("since_minutes", 60)
        limit = min(kwargs.get("limit", 20), 100)
        since_dt, until_dt = resolve_time_range(
            since_minutes, kwargs.get("since"), kwargs.get("until"),
        )

        try:
            from argus_agent.storage.repositories import get_metrics_repository

            repo = get_metrics_repository()
            slow = repo.query_slow_spans(
                service=service, since_minutes=since_minutes, limit=limit,
                since_dt=since_dt, until_dt=until_dt,
            )
            summary = repo.query_trace_summary(
                service=service, since_minutes=since_minutes,
                since_dt=since_dt, until_dt=until_dt,
            )
        except RuntimeError:
            return {"error": "Time-series store not initialized"}

        return {
            "slowest_spans": slow,
            "summary_by_name": summary,
            "since_minutes": since_minutes,
            "display_type": "table",
        }


class RequestMetricsTool(Tool):
    """Aggregate HTTP request spans into time-bucketed endpoint metrics."""

    @property
    def name(self) -> str:
        return "query_request_metrics"

    @property
    def description(self) -> str:
        return (
            "Aggregate HTTP request performance metrics from traced spans. "
            "Returns per-bucket: request_count, error_count, error_rate, "
            "p50/p95/p99 duration. Filter by service, path, method, time range."
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
                "path": {
                    "type": "string",
                    "description": "Filter by HTTP path (e.g. /api/users)",
                },
                "method": {
                    "type": "string",
                    "description": "Filter by HTTP method (e.g. GET, POST)",
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
                    "description": "Bucket size in minutes (default 5)",
                    "default": 5,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        since_dt, until_dt = resolve_time_range(
            kwargs.get("since_minutes", 60), kwargs.get("since"), kwargs.get("until"),
        )
        try:
            from argus_agent.storage.repositories import get_metrics_repository

            buckets = get_metrics_repository().query_request_metrics(
                service=kwargs.get("service", ""),
                path=kwargs.get("path", ""),
                method=kwargs.get("method", ""),
                since_minutes=kwargs.get("since_minutes", 60),
                interval_minutes=kwargs.get("interval_minutes", 5),
                since_dt=since_dt,
                until_dt=until_dt,
            )
        except RuntimeError:
            return {"error": "Time-series store not initialized", "buckets": []}

        return {
            "buckets": buckets,
            "count": len(buckets),
            "display_type": "table",
        }


def register_trace_tools() -> None:
    """Register trace analysis tools."""
    from argus_agent.tools.base import register_tool

    register_tool(TraceTimelineTool())
    register_tool(SlowTraceAnalysisTool())
    register_tool(RequestMetricsTool())
