"""System metrics query tool."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import psutil

from argus_agent.storage.timeseries import query_metrics, query_metrics_summary
from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.metrics")

# Time range shortcuts
_TIME_RANGES: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


class SystemMetricsTool(Tool):
    """Query current and historical system metrics."""

    @property
    def name(self) -> str:
        return "system_metrics"

    @property
    def description(self) -> str:
        return (
            "Get system metrics (CPU, memory, disk, network, load). "
            "Can show current values or historical data over a time range."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "description": (
                        "Metric name. Options: cpu_percent, memory_percent, "
                        "disk_percent, load_1m, load_5m, load_15m, "
                        "swap_percent, net_bytes_sent_per_sec, "
                        "net_bytes_recv_per_sec. Use 'all' for a full snapshot."
                    ),
                    "default": "all",
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range: 5m, 15m, 30m, 1h, 6h, 24h, 7d (default: current)",
                },
                "include_summary": {
                    "type": "boolean",
                    "description": "Include min/max/avg summary (default: true for historical)",
                    "default": True,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        metric = kwargs.get("metric", "all")
        time_range = kwargs.get("time_range")
        include_summary = kwargs.get("include_summary", True)

        # Current snapshot
        if metric == "all" and not time_range:
            return self._current_snapshot()

        # Historical query
        if time_range:
            delta = _TIME_RANGES.get(time_range)
            if not delta:
                return {"error": f"Invalid time_range. Use: {', '.join(_TIME_RANGES)}"}

            since = datetime.now(UTC) - delta

            if metric == "all":
                # Summary for key metrics
                result: dict[str, Any] = {"time_range": time_range, "metrics": {}}
                for m in ("cpu_percent", "memory_percent", "disk_percent", "load_1m"):
                    result["metrics"][m] = query_metrics_summary(m, since=since)
                return result

            data: dict[str, Any] = {"metric": metric, "time_range": time_range}
            if include_summary:
                data["summary"] = query_metrics_summary(metric, since=since)
            data["data_points"] = query_metrics(metric, since=since, limit=100)
            data["display_type"] = "metrics_chart"
            return data

        # Current specific metric
        return self._current_snapshot(metric)

    def _current_snapshot(self, metric: str = "all") -> dict[str, Any]:
        """Get current system metrics from psutil."""
        result: dict[str, Any] = {}

        if metric in ("all", "cpu_percent"):
            result["cpu_percent"] = psutil.cpu_percent(interval=None)
            result["cpu_count"] = psutil.cpu_count()
            result["cpu_per_core"] = psutil.cpu_percent(interval=None, percpu=True)

        if metric in ("all", "memory_percent"):
            mem = psutil.virtual_memory()
            result["memory_percent"] = mem.percent
            result["memory_used_gb"] = round(mem.used / (1024**3), 2)
            result["memory_total_gb"] = round(mem.total / (1024**3), 2)
            result["memory_available_gb"] = round(mem.available / (1024**3), 2)

        if metric in ("all", "disk_percent"):
            try:
                disk = psutil.disk_usage("/")
                result["disk_percent"] = disk.percent
                result["disk_used_gb"] = round(disk.used / (1024**3), 2)
                result["disk_total_gb"] = round(disk.total / (1024**3), 2)
                result["disk_free_gb"] = round(disk.free / (1024**3), 2)
            except OSError:
                result["disk_error"] = "Unable to read disk usage"

        if metric in ("all", "load_1m", "load_5m", "load_15m"):
            try:
                load1, load5, load15 = __import__("os").getloadavg()
                result["load_1m"] = round(load1, 2)
                result["load_5m"] = round(load5, 2)
                result["load_15m"] = round(load15, 2)
            except OSError:
                pass

        if metric in ("all", "swap_percent"):
            swap = psutil.swap_memory()
            result["swap_percent"] = swap.percent
            result["swap_used_gb"] = round(swap.used / (1024**3), 2)

        result["display_type"] = "metrics_chart"
        return result


def register_metrics_tools() -> None:
    """Register metrics tools."""
    from argus_agent.tools.base import register_tool

    register_tool(SystemMetricsTool())
