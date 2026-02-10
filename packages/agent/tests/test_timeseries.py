"""Tests for DuckDB time-series storage helpers."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from argus_agent.storage.timeseries import (
    close_timeseries,
    init_timeseries,
    insert_log_entry,
    insert_metric,
    insert_metrics_batch,
    query_latest_metrics,
    query_log_entries,
    query_metrics,
    query_metrics_summary,
)


@pytest.fixture(autouse=True)
def _ts_db():
    """Create a temp DuckDB for each test."""
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "test_ts.duckdb")
        init_timeseries(db_path)
        yield
        close_timeseries()


class TestInsertAndQueryMetrics:
    def test_insert_single_metric(self):
        insert_metric("cpu_percent", 42.5)
        results = query_metrics("cpu_percent")
        assert len(results) == 1
        assert results[0]["value"] == 42.5
        assert results[0]["metric_name"] == "cpu_percent"

    def test_insert_with_labels(self):
        insert_metric("disk_percent", 80.0, labels={"mount": "/"})
        results = query_metrics("disk_percent")
        assert len(results) == 1
        assert results[0]["labels"]["mount"] == "/"

    def test_insert_batch(self):
        now = datetime.now(UTC)
        rows = [
            (now - timedelta(seconds=30), "cpu_percent", 50.0, None),
            (now - timedelta(seconds=15), "cpu_percent", 55.0, None),
            (now, "cpu_percent", 60.0, None),
        ]
        insert_metrics_batch(rows)
        results = query_metrics("cpu_percent")
        assert len(results) == 3

    def test_insert_batch_empty(self):
        insert_metrics_batch([])
        results = query_metrics("cpu_percent")
        assert len(results) == 0

    def test_query_with_time_filter(self):
        now = datetime.now(UTC)
        insert_metric("cpu_percent", 50.0, timestamp=now - timedelta(hours=2))
        insert_metric("cpu_percent", 60.0, timestamp=now - timedelta(minutes=5))
        insert_metric("cpu_percent", 70.0, timestamp=now)

        recent = query_metrics("cpu_percent", since=now - timedelta(hours=1))
        assert len(recent) == 2

    def test_query_with_limit(self):
        now = datetime.now(UTC)
        for i in range(10):
            insert_metric("cpu_percent", float(i), timestamp=now - timedelta(seconds=i))
        results = query_metrics("cpu_percent", limit=5)
        assert len(results) == 5

    def test_query_nonexistent_metric(self):
        results = query_metrics("nonexistent")
        assert len(results) == 0


class TestMetricsSummary:
    def test_summary_basic(self):
        now = datetime.now(UTC)
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            insert_metric("cpu_percent", v, timestamp=now)

        summary = query_metrics_summary("cpu_percent")
        assert summary["count"] == 5
        assert summary["min"] == 10.0
        assert summary["max"] == 50.0
        assert summary["avg"] == 30.0

    def test_summary_empty(self):
        summary = query_metrics_summary("nonexistent")
        assert summary["count"] == 0

    def test_summary_with_time_filter(self):
        now = datetime.now(UTC)
        insert_metric("mem", 50.0, timestamp=now - timedelta(hours=2))
        insert_metric("mem", 90.0, timestamp=now)

        summary = query_metrics_summary("mem", since=now - timedelta(hours=1))
        assert summary["count"] == 1
        assert summary["avg"] == 90.0


class TestLatestMetrics:
    def test_latest(self):
        now = datetime.now(UTC)
        insert_metric("cpu_percent", 50.0, timestamp=now - timedelta(seconds=30))
        insert_metric("cpu_percent", 70.0, timestamp=now)
        insert_metric("memory_percent", 80.0, timestamp=now)

        latest = query_latest_metrics()
        assert latest["cpu_percent"] == 70.0
        assert latest["memory_percent"] == 80.0


class TestLogEntries:
    def test_insert_and_query(self):
        insert_log_entry(
            file_path="/var/log/syslog",
            line_offset=1000,
            severity="ERROR",
            message_preview="Connection refused",
        )
        results = query_log_entries()
        assert len(results) == 1
        assert results[0]["severity"] == "ERROR"
        assert "Connection refused" in results[0]["message_preview"]

    def test_filter_by_severity(self):
        insert_log_entry("/var/log/syslog", 100, severity="ERROR")
        insert_log_entry("/var/log/syslog", 200, severity="INFO")
        insert_log_entry("/var/log/syslog", 300, severity="ERROR")

        errors = query_log_entries(severity="ERROR")
        assert len(errors) == 2

    def test_filter_by_file(self):
        insert_log_entry("/var/log/syslog", 100)
        insert_log_entry("/var/log/auth.log", 200)

        results = query_log_entries(file_path="/var/log/auth.log")
        assert len(results) == 1
