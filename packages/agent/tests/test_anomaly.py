"""Tests for anomaly detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from argus_agent.baseline.anomaly import COOLDOWN_SECONDS, AnomalyDetector
from argus_agent.baseline.tracker import BaselineTracker, MetricBaseline
from argus_agent.events.types import EventSeverity


@pytest.fixture
def tracker():
    t = BaselineTracker()
    # Inject known baselines directly
    t._baselines = {
        "cpu_percent": MetricBaseline(
            metric_name="cpu_percent",
            mean=50.0,
            stddev=10.0,
            min=20.0,
            max=80.0,
            p50=50.0,
            p95=70.0,
            p99=78.0,
            sample_count=100,
        ),
        "memory_percent": MetricBaseline(
            metric_name="memory_percent",
            mean=60.0,
            stddev=5.0,
            min=50.0,
            max=70.0,
            p50=60.0,
            p95=68.0,
            p99=69.0,
            sample_count=100,
        ),
    }
    return t


@pytest.fixture
def detector(tracker):
    return AnomalyDetector(tracker)


def test_no_anomaly_within_normal_range(detector: AnomalyDetector):
    """Value within 2 stddev -> no anomaly."""
    result = detector.check_metric("cpu_percent", 65.0)  # z = 1.5
    assert result is None


def test_notable_anomaly(detector: AnomalyDetector):
    """z > 2 and <= 3 -> NOTABLE."""
    result = detector.check_metric("cpu_percent", 75.0)  # z = 2.5
    assert result is not None
    assert result.severity == EventSeverity.NOTABLE
    assert result.z_score == 2.5
    assert result.metric_name == "cpu_percent"


def test_urgent_anomaly(detector: AnomalyDetector):
    """z > 3 -> URGENT."""
    result = detector.check_metric("cpu_percent", 85.0)  # z = 3.5
    assert result is not None
    assert result.severity == EventSeverity.URGENT
    assert result.z_score == 3.5


def test_anomaly_below_mean(detector: AnomalyDetector):
    """Anomaly detection works for values below the mean too."""
    result = detector.check_metric("cpu_percent", 15.0)  # z = 3.5
    assert result is not None
    assert result.severity == EventSeverity.URGENT


def test_no_baseline_returns_none(detector: AnomalyDetector):
    """Unknown metric -> None."""
    result = detector.check_metric("nonexistent_metric", 99.0)
    assert result is None


def test_zero_stddev_returns_none(tracker: BaselineTracker):
    """Zero stddev -> None (can't compute z-score)."""
    tracker._baselines["flat"] = MetricBaseline(
        metric_name="flat", mean=50.0, stddev=0.0,
        min=50.0, max=50.0, p50=50.0, p95=50.0, p99=50.0, sample_count=100,
    )
    detector = AnomalyDetector(tracker)
    result = detector.check_metric("flat", 55.0)
    assert result is None


def test_cooldown_suppresses_repeat(detector: AnomalyDetector):
    """Second alert within cooldown period is suppressed."""
    result1 = detector.check_metric("cpu_percent", 85.0)
    assert result1 is not None

    # Immediate second check -> suppressed
    result2 = detector.check_metric("cpu_percent", 85.0)
    assert result2 is None


def test_cooldown_expires(detector: AnomalyDetector):
    """Alert fires again after cooldown period expires."""
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    later = now + timedelta(seconds=COOLDOWN_SECONDS + 1)

    with patch("argus_agent.baseline.anomaly.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result1 = detector.check_metric("cpu_percent", 85.0)
        assert result1 is not None

        # After cooldown
        mock_dt.now.return_value = later
        result2 = detector.check_metric("cpu_percent", 85.0)
        assert result2 is not None


def test_check_all_current(detector: AnomalyDetector):
    """check_all_current returns anomalies for all abnormal metrics."""
    metrics = {
        "cpu_percent": 85.0,  # z=3.5 -> anomaly
        "memory_percent": 62.0,  # z=0.4 -> normal
    }
    anomalies = detector.check_all_current(metrics)
    assert len(anomalies) == 1
    assert anomalies[0].metric_name == "cpu_percent"


def test_anomaly_message_format(detector: AnomalyDetector):
    result = detector.check_metric("cpu_percent", 85.0)
    assert result is not None
    assert "cpu_percent=85.0" in result.message
    assert "z=3.5" in result.message
    assert "mean=50.0" in result.message
