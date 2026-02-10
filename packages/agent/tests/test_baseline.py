"""Tests for the baseline tracker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from argus_agent.baseline.tracker import BaselineTracker


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_ts.duckdb")


@pytest.fixture
def setup_db(db_path):
    """Set up a temp DuckDB with system_metrics and metric_baselines tables."""
    from argus_agent.storage import timeseries

    timeseries.init_timeseries(db_path)
    yield
    timeseries.close_timeseries()


@pytest.fixture
def tracker(setup_db):
    return BaselineTracker()


def _insert_synthetic_data(metric_name: str, values: list[float], hours_ago: int = 1):
    """Insert synthetic metric data points."""
    from argus_agent.storage.timeseries import get_connection

    conn = get_connection()
    base_time = datetime.now(UTC) - timedelta(hours=hours_ago)
    for i, val in enumerate(values):
        ts = base_time + timedelta(minutes=i)
        conn.execute(
            "INSERT INTO system_metrics VALUES (?, ?, ?, ?)",
            [ts, metric_name, val, "{}"],
        )


def test_update_baselines_empty_db(tracker: BaselineTracker):
    """No data -> no baselines."""
    tracker.update_baselines()
    assert tracker.get_baseline("cpu_percent") is None


def test_update_baselines_insufficient_samples(tracker: BaselineTracker):
    """Fewer than 10 samples -> metric excluded."""
    _insert_synthetic_data("cpu_percent", [50.0] * 9)
    tracker.update_baselines()
    assert tracker.get_baseline("cpu_percent") is None


def test_update_baselines_computes_stats(tracker: BaselineTracker):
    """Sufficient data -> correct stats computed via SQL."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    _insert_synthetic_data("cpu_percent", values)
    tracker.update_baselines()

    bl = tracker.get_baseline("cpu_percent")
    assert bl is not None
    assert bl.metric_name == "cpu_percent"
    assert bl.sample_count == 10
    assert bl.mean == pytest.approx(55.0, abs=0.1)
    assert bl.min == pytest.approx(10.0)
    assert bl.max == pytest.approx(100.0)
    assert bl.stddev > 0


def test_update_baselines_multiple_metrics(tracker: BaselineTracker):
    """Multiple metrics get independent baselines."""
    _insert_synthetic_data("cpu_percent", [50.0] * 20)
    _insert_synthetic_data("memory_percent", [70.0] * 15)

    tracker.update_baselines()

    cpu_bl = tracker.get_baseline("cpu_percent")
    mem_bl = tracker.get_baseline("memory_percent")
    assert cpu_bl is not None
    assert mem_bl is not None
    assert cpu_bl.mean == pytest.approx(50.0)
    assert mem_bl.mean == pytest.approx(70.0)


def test_baselines_persisted_to_duckdb(tracker: BaselineTracker):
    """Baselines get written to the metric_baselines table."""
    from argus_agent.storage.timeseries import get_connection

    _insert_synthetic_data("cpu_percent", [50.0] * 20)
    tracker.update_baselines()

    conn = get_connection()
    rows = conn.execute("SELECT metric_name, mean FROM metric_baselines").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "cpu_percent"
    assert rows[0][1] == pytest.approx(50.0)


def test_format_for_prompt_empty(tracker: BaselineTracker):
    assert tracker.format_for_prompt() == ""


def test_format_for_prompt_with_data(tracker: BaselineTracker):
    _insert_synthetic_data("cpu_percent", [50.0] * 20)
    tracker.update_baselines()

    text = tracker.format_for_prompt()
    assert "cpu_percent" in text
    assert "mean=" in text
    assert "p95=" in text


def test_old_data_excluded(tracker: BaselineTracker):
    """Data older than 7 days is excluded from baseline computation."""
    from argus_agent.storage.timeseries import get_connection

    conn = get_connection()
    old_time = datetime.now(UTC) - timedelta(days=10)
    for i in range(20):
        ts = old_time + timedelta(minutes=i)
        conn.execute(
            "INSERT INTO system_metrics VALUES (?, ?, ?, ?)",
            [ts, "old_metric", 99.0, "{}"],
        )

    tracker.update_baselines()
    assert tracker.get_baseline("old_metric") is None
