"""Chart generation tool for data visualization."""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.chart")


class GenerateChartTool(Tool):
    """Generate chart visualizations from data."""

    @property
    def name(self) -> str:
        return "generate_chart"

    @property
    def description(self) -> str:
        return (
            "Generate a chart visualization from data. "
            "Use after querying data with other tools. Supports: "
            "line (time-series, x_key + y_keys), "
            "bar (categorical comparison, x_key + y_keys), "
            "pie (distribution, name_key + value_key). "
            "Supports multi-series: pass multiple y_keys to render "
            "multiple lines or bar groups."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["line", "bar", "pie"],
                    "description": "Chart type: line, bar, or pie",
                },
                "chart_title": {
                    "type": "string",
                    "description": "Chart title displayed above the chart",
                },
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Array of data point objects",
                },
                "x_key": {
                    "type": "string",
                    "description": "Field name for x-axis (line/bar). Default: 'name'",
                },
                "y_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Field names for data series (line/bar). Default: ['value']. "
                        "Use multiple entries for multi-series charts."
                    ),
                },
                "name_key": {
                    "type": "string",
                    "description": "Field name for slice labels (pie). Default: 'name'",
                },
                "value_key": {
                    "type": "string",
                    "description": "Field name for slice values (pie). Default: 'value'",
                },
                "unit": {
                    "type": "string",
                    "description": "Unit suffix for values (e.g. '%', 'GB', 'ms')",
                },
            },
            "required": ["chart_type", "chart_title", "data"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        chart_type = kwargs.get("chart_type")
        title = kwargs.get("chart_title", "")
        data = kwargs.get("data")

        if not isinstance(data, list) or len(data) == 0:
            return {"error": "data must be a non-empty array of objects"}

        if chart_type not in ("line", "bar", "pie"):
            return {"error": "chart_type must be 'line', 'bar', or 'pie'"}

        result: dict[str, Any] = {
            "display_type": "chart",
            "chart_type": chart_type,
            "title": title,
            "data": data,
        }

        if chart_type in ("line", "bar"):
            result["x_key"] = kwargs.get("x_key", "name")
            result["y_keys"] = kwargs.get("y_keys", ["value"])
        else:
            result["name_key"] = kwargs.get("name_key", "name")
            result["value_key"] = kwargs.get("value_key", "value")

        unit = kwargs.get("unit")
        if unit:
            result["unit"] = unit

        return result


def register_chart_tools() -> None:
    """Register chart tools."""
    from argus_agent.tools.base import register_tool

    register_tool(GenerateChartTool())
