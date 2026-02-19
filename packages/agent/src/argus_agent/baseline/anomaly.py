"""Statistical anomaly detection using z-scores and moving averages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from argus_agent.baseline.tracker import BaselineTracker
from argus_agent.events.types import EventSeverity

logger = logging.getLogger("argus.baseline.anomaly")

# Cooldown period to prevent alert storms (per metric)
COOLDOWN_SECONDS = 900  # 15 minutes

# Z-score thresholds
Z_NOTABLE = 2.0
Z_URGENT = 3.0


@dataclass
class Anomaly:
    """A detected anomaly for a single metric."""

    metric_name: str
    value: float
    z_score: float
    severity: EventSeverity
    message: str
    baseline_mean: float = 0.0


class AnomalyDetector:
    """Compares live metrics against baselines using z-score analysis.

    * z > 2.0 (and <= 3.0): ``NOTABLE``
    * z > 3.0: ``URGENT``

    A per-metric cooldown prevents the same anomaly from being reported
    more than once every 15 minutes.
    """

    def __init__(self, tracker: BaselineTracker) -> None:
        self._tracker = tracker
        self._last_fired: dict[str, datetime] = {}

    def check_metric(self, name: str, value: float) -> Anomaly | None:
        """Check a single metric value against its baseline.

        Returns an ``Anomaly`` if the value exceeds z-score thresholds
        and the cooldown has expired, otherwise ``None``.
        """
        bl = self._tracker.get_baseline(name)
        if bl is None or bl.stddev == 0:
            return None

        z = abs(value - bl.mean) / bl.stddev
        if z <= Z_NOTABLE:
            return None

        # Cooldown check
        now = datetime.now(UTC)
        last = self._last_fired.get(name)
        if last and (now - last).total_seconds() < COOLDOWN_SECONDS:
            return None

        if z > Z_URGENT:
            severity = EventSeverity.URGENT
        else:
            severity = EventSeverity.NOTABLE

        self._last_fired[name] = now

        return Anomaly(
            metric_name=name,
            value=value,
            z_score=round(z, 2),
            severity=severity,
            message=(
                f"Anomaly: {name}={value:.1f} "
                f"(z={z:.1f}, baseline mean={bl.mean:.1f}, stddev={bl.stddev:.1f})"
            ),
            baseline_mean=round(bl.mean, 1),
        )

    def check_all_current(self, metrics: dict[str, float]) -> list[Anomaly]:
        """Check all metrics in a dict, returning any detected anomalies."""
        anomalies: list[Anomaly] = []
        for name, value in metrics.items():
            a = self.check_metric(name, value)
            if a is not None:
                anomalies.append(a)
        return anomalies
