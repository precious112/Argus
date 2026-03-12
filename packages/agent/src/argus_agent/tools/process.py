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
            "List ALL running processes with CPU and memory usage. "
            "Returns every process — no filtering, no limits."
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
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        sort_by = kwargs.get("sort_by", "cpu_percent")

        processes = get_process_list(sort_by=sort_by)

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
