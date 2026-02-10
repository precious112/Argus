"""Tests for Phase 2 tools: system_metrics, process_list, network_connections."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from argus_agent.config import reset_settings
from argus_agent.events.bus import reset_event_bus
from argus_agent.storage.timeseries import close_timeseries, init_timeseries
from argus_agent.tools.metrics import SystemMetricsTool
from argus_agent.tools.network import NetworkConnectionsTool
from argus_agent.tools.process import ProcessListTool


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    reset_event_bus()
    yield
    reset_settings()
    reset_event_bus()


@pytest.fixture()
def _ts_db():
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "test_ts.duckdb")
        init_timeseries(db_path)
        yield
        close_timeseries()


class TestSystemMetricsTool:
    @pytest.mark.asyncio
    async def test_current_snapshot(self, _ts_db):
        tool = SystemMetricsTool()
        result = await tool.execute()

        assert "cpu_percent" in result
        assert "memory_percent" in result
        assert "display_type" in result

    @pytest.mark.asyncio
    async def test_specific_metric(self, _ts_db):
        tool = SystemMetricsTool()
        result = await tool.execute(metric="cpu_percent")

        assert "cpu_percent" in result
        assert "memory_percent" not in result

    @pytest.mark.asyncio
    async def test_invalid_time_range(self, _ts_db):
        tool = SystemMetricsTool()
        result = await tool.execute(metric="cpu_percent", time_range="invalid")

        assert "error" in result

    def test_tool_properties(self):
        tool = SystemMetricsTool()
        assert tool.name == "system_metrics"
        assert tool.risk.value == "READ_ONLY"

    def test_definition(self):
        tool = SystemMetricsTool()
        defn = tool.to_definition()
        assert defn.name == "system_metrics"
        assert "metric" in defn.parameters["properties"]


class TestProcessListTool:
    @pytest.mark.asyncio
    async def test_list_processes(self):
        tool = ProcessListTool()
        result = await tool.execute()

        assert "processes" in result
        assert "total_processes" in result
        assert len(result["processes"]) > 0
        assert "pid" in result["processes"][0]
        assert result["display_type"] == "process_table"

    @pytest.mark.asyncio
    async def test_limit(self):
        tool = ProcessListTool()
        result = await tool.execute(limit=3)

        assert len(result["processes"]) <= 3

    @pytest.mark.asyncio
    async def test_filter_name(self):
        tool = ProcessListTool()
        result = await tool.execute(filter_name="python", limit=100)

        for p in result["processes"]:
            assert "python" in p["name"].lower() or "python" in p.get("cmdline", "").lower()

    def test_tool_properties(self):
        tool = ProcessListTool()
        assert tool.name == "process_list"
        assert tool.risk.value == "READ_ONLY"


class TestNetworkConnectionsTool:
    @pytest.mark.asyncio
    async def test_list_connections(self):
        tool = NetworkConnectionsTool()
        result = await tool.execute()

        if "error" in result:
            # psutil.net_connections() needs root on macOS
            assert "Access denied" in result["error"]
        else:
            assert "connections" in result
            assert "total_connections" in result
            assert result["display_type"] == "process_table"

    @pytest.mark.asyncio
    async def test_filter_listening(self):
        tool = NetworkConnectionsTool()
        result = await tool.execute(kind="listening")

        if "error" in result:
            pytest.skip("net_connections requires elevated privileges")

        for conn in result["connections"]:
            assert conn["status"] == "LISTEN"

    def test_tool_properties(self):
        tool = NetworkConnectionsTool()
        assert tool.name == "network_connections"
        assert tool.risk.value == "READ_ONLY"
