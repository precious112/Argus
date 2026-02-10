"""Process list and management tools."""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.collectors.process_monitor import get_process_list
from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.process")


class ProcessListTool(Tool):
    """List running processes with resource usage."""

    @property
    def name(self) -> str:
        return "process_list"

    @property
    def description(self) -> str:
        return (
            "List running processes with CPU and memory usage. "
            "Sort by cpu_percent, memory_percent, or pid."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sort_by": {
                    "type": "string",
                    "description": "Sort: cpu_percent, memory_percent, pid",
                    "default": "cpu_percent",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max processes to return (default: 25)",
                    "default": 25,
                },
                "filter_name": {
                    "type": "string",
                    "description": "Filter by process name (substring match)",
                },
                "filter_user": {
                    "type": "string",
                    "description": "Filter by username",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        sort_by = kwargs.get("sort_by", "cpu_percent")
        limit = min(kwargs.get("limit", 25), 100)
        filter_name = kwargs.get("filter_name", "")
        filter_user = kwargs.get("filter_user", "")

        processes = get_process_list(sort_by=sort_by, limit=200)

        # Apply filters
        if filter_name:
            fn = filter_name.lower()
            processes = [
                p
                for p in processes
                if fn in p.get("name", "").lower() or fn in p.get("cmdline", "").lower()
            ]
        if filter_user:
            processes = [p for p in processes if p.get("username") == filter_user]

        processes = processes[:limit]

        return {
            "total_processes": len(processes),
            "sort_by": sort_by,
            "processes": processes,
            "display_type": "process_table",
        }


def register_process_tools() -> None:
    """Register process tools."""
    from argus_agent.tools.base import register_tool

    register_tool(ProcessListTool())
