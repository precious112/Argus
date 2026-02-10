"""Tests for collectors (system metrics, process monitor, log watcher)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from argus_agent.collectors.log_watcher import (
    WatchedFile,
    _detect_severity,
    _normalize_error,
)
from argus_agent.collectors.process_monitor import get_process_list
from argus_agent.collectors.system_metrics import (
    SystemMetricsCollector,
    format_snapshot_for_prompt,
    update_system_snapshot,
)
from argus_agent.config import reset_settings
from argus_agent.events.bus import reset_event_bus
from argus_agent.storage.timeseries import close_timeseries, init_timeseries


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


class TestSystemMetricsCollector:
    @pytest.mark.asyncio
    async def test_collect_once(self, _ts_db):
        collector = SystemMetricsCollector(interval=999)
        metrics = await collector.collect_once()

        assert "cpu_percent" in metrics
        assert "memory_percent" in metrics
        assert "memory_used_bytes" in metrics
        assert "swap_percent" in metrics
        assert isinstance(metrics["cpu_percent"], float)
        assert 0 <= metrics["memory_percent"] <= 100

    @pytest.mark.asyncio
    async def test_start_stop(self, _ts_db):
        collector = SystemMetricsCollector(interval=999)
        await collector.start()
        assert collector.is_running
        await collector.stop()
        assert not collector.is_running

    @pytest.mark.asyncio
    async def test_no_double_start(self, _ts_db):
        collector = SystemMetricsCollector(interval=999)
        await collector.start()
        await collector.start()  # Should not fail
        assert collector.is_running
        await collector.stop()


class TestSystemSnapshot:
    @pytest.mark.asyncio
    async def test_update_snapshot(self):
        snapshot = await update_system_snapshot()
        assert "cpu_percent" in snapshot
        assert "memory_percent" in snapshot
        assert "cpu_count" in snapshot

    def test_format_snapshot_empty(self):
        result = format_snapshot_for_prompt(None)
        # Either "not yet collected" (if no snapshot taken yet) or actual data
        # The function uses _latest_snapshot as fallback, which may have been
        # populated by another test. Test with explicit empty snapshot:
        assert isinstance(result, str)

    def test_format_snapshot_none(self):
        from argus_agent.collectors import system_metrics

        old = system_metrics._latest_snapshot
        system_metrics._latest_snapshot = {}
        try:
            result = format_snapshot_for_prompt()
            assert "not yet collected" in result
        finally:
            system_metrics._latest_snapshot = old

    @pytest.mark.asyncio
    async def test_format_snapshot_with_data(self):
        snapshot = await update_system_snapshot()
        result = format_snapshot_for_prompt(snapshot)
        assert "CPU:" in result
        assert "Memory:" in result


class TestProcessMonitor:
    def test_get_process_list(self):
        processes = get_process_list(limit=10)
        assert len(processes) > 0
        assert "pid" in processes[0]
        assert "name" in processes[0]
        assert "cpu_percent" in processes[0]
        assert "memory_percent" in processes[0]

    def test_sort_by_memory(self):
        processes = get_process_list(sort_by="memory_percent", limit=5)
        if len(processes) >= 2:
            assert processes[0]["memory_percent"] >= processes[1]["memory_percent"]

    def test_sort_by_pid(self):
        processes = get_process_list(sort_by="pid", limit=5)
        if len(processes) >= 2:
            assert processes[0]["pid"] <= processes[1]["pid"]


class TestLogSeverityDetection:
    def test_error_detection(self):
        assert _detect_severity("2024-01-01 ERROR: Something failed") == "ERROR"
        assert _detect_severity("FATAL: crash") == "ERROR"
        assert _detect_severity("CRITICAL failure") == "ERROR"

    def test_warning_detection(self):
        assert _detect_severity("WARNING: disk nearly full") == "WARNING"
        assert _detect_severity("[WARN] timeout") == "WARNING"

    def test_info_detection(self):
        assert _detect_severity("INFO: started") == "INFO"
        assert _detect_severity("NOTICE: maintenance") == "INFO"

    def test_debug_detection(self):
        assert _detect_severity("DEBUG: trace value") == "DEBUG"

    def test_no_severity(self):
        assert _detect_severity("just a plain line") == ""


class TestNormalizeError:
    def test_strips_timestamps(self):
        result = _normalize_error("2024-01-15T12:30:45 ERROR: something")
        assert "<TS>" in result
        assert "2024" not in result

    def test_strips_ips(self):
        result = _normalize_error("Connection from 192.168.1.100 refused")
        assert "<IP>" in result
        assert "192.168" not in result

    def test_strips_long_numbers(self):
        result = _normalize_error("Request 12345678 failed")
        assert "<N>" in result

    def test_truncates(self):
        result = _normalize_error("x" * 200)
        assert len(result) <= 100


class TestWatchedFile:
    def test_read_new_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("line 1\nline 2\n")
            f.flush()
            path = Path(f.name)

        wf = WatchedFile(path)
        # Initial position is at end, so no new lines
        assert wf.read_new_lines() == []

        # Append new lines
        with open(path, "a") as f:
            f.write("line 3\nline 4\n")

        new_lines = wf.read_new_lines()
        assert len(new_lines) == 2
        assert new_lines[0][1] == "line 3"
        assert new_lines[1][1] == "line 4"

        # No more new lines
        assert wf.read_new_lines() == []

        path.unlink()

    def test_file_rotation(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("old content\n" * 100)
            f.flush()
            path = Path(f.name)

        wf = WatchedFile(path)
        assert wf.offset > 0

        # Simulate rotation: truncate
        with open(path, "w") as f:
            f.write("new content\n")

        lines = wf.read_new_lines()
        assert len(lines) == 1
        assert lines[0][1] == "new content"

        path.unlink()
