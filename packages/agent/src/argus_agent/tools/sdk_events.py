"""Query SDK telemetry events tool."""

from __future__ import annotations

import json
import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk, resolve_time_range

logger = logging.getLogger("argus.tools.sdk_events")


class SDKEventsTool(Tool):
    """Query SDK telemetry events from monitored applications."""

    @property
    def name(self) -> str:
        return "query_sdk_events"

    @property
    def description(self) -> str:
        return (
            "Query telemetry events sent by applications using the Argus SDK. "
            "Shows logs, exceptions, spans, dependencies, runtime metrics, deploys, "
            "breadcrumbs, and custom events from instrumented apps. "
            "Filter by service name, event type, and time range."
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
                "event_type": {
                    "type": "string",
                    "description": (
                        "Filter by type: log, exception, event, span, "
                        "dependency, runtime_metric, deploy, breadcrumb"
                    ),
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
                    "description": "Max events to return (default 50)",
                    "default": 50,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service", "")
        event_type = kwargs.get("event_type", "")
        since_minutes = kwargs.get("since_minutes", 60)
        limit = min(kwargs.get("limit", 50), 200)

        try:
            from argus_agent.storage.repositories import get_metrics_repository

            repo = get_metrics_repository()
        except RuntimeError:
            return {"error": "Time-series store not initialized", "events": []}

        since_dt, until_dt = resolve_time_range(
            since_minutes, kwargs.get("since"), kwargs.get("until"),
        )

        conditions = []
        params: list[Any] = []

        conditions.append("timestamp >= ?")
        params.append(since_dt)

        if until_dt:
            conditions.append("timestamp <= ?")
            params.append(until_dt)

        if service:
            conditions.append("service = ?")
            params.append(service)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        where = " AND ".join(conditions)
        params.append(limit)

        result = repo.execute_raw(
            f"SELECT timestamp, service, event_type, data FROM sdk_events "  # noqa: S608
            f"WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )

        events = []
        for row in result:
            data = row[3]
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    pass
            events.append({
                "timestamp": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "service": row[1],
                "type": row[2],
                "data": data,
            })

        return {
            "events": events,
            "count": len(events),
            "since_minutes": since_minutes,
            "display_type": "table",
        }


def register_sdk_tools() -> None:
    """Register SDK event tools."""
    from argus_agent.tools.base import register_tool

    register_tool(SDKEventsTool())
