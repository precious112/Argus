"""Rule-based event classifier: Normal/Notable/Urgent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from argus_agent.events.types import Event, EventSeverity, EventType

logger = logging.getLogger("argus.events.classifier")


@dataclass
class ThresholdRule:
    """A threshold-based classification rule."""

    metric: str
    notable_threshold: float
    urgent_threshold: float
    message_template: str


# Default threshold rules for common metrics
DEFAULT_THRESHOLDS: list[ThresholdRule] = [
    ThresholdRule(
        metric="cpu_percent",
        notable_threshold=80.0,
        urgent_threshold=95.0,
        message_template="CPU usage at {value:.1f}%",
    ),
    ThresholdRule(
        metric="memory_percent",
        notable_threshold=85.0,
        urgent_threshold=95.0,
        message_template="Memory usage at {value:.1f}%",
    ),
    ThresholdRule(
        metric="disk_percent",
        notable_threshold=85.0,
        urgent_threshold=95.0,
        message_template="Disk usage at {value:.1f}%",
    ),
    ThresholdRule(
        metric="load_per_cpu",
        notable_threshold=1.5,
        urgent_threshold=3.0,
        message_template="Load per CPU at {value:.2f}",
    ),
]


class EventClassifier:
    """Rule-based event classifier (Tier 1 intelligence).

    Classifies events as NORMAL, NOTABLE, or URGENT based on
    configurable threshold rules. Zero LLM cost.
    """

    def __init__(self, thresholds: list[ThresholdRule] | None = None) -> None:
        self._thresholds = {r.metric: r for r in (thresholds or DEFAULT_THRESHOLDS)}
        self._error_window: list[float] = []
        self._error_window_seconds = 60.0
        self._error_burst_threshold = 10

    def classify(self, event: Event) -> Event:
        """Classify an event and set its severity. Returns the event (mutated)."""
        # Already classified as non-NORMAL by the source — keep it
        if event.severity != EventSeverity.NORMAL:
            return event

        # Metric threshold classification
        if event.type == EventType.METRIC_COLLECTED:
            self._classify_metric(event)

        # Process events
        elif event.type == EventType.PROCESS_CRASHED:
            event.severity = EventSeverity.URGENT
        elif event.type == EventType.PROCESS_OOM_KILLED:
            event.severity = EventSeverity.URGENT
        elif event.type == EventType.PROCESS_RESTART_LOOP:
            event.severity = EventSeverity.NOTABLE

        # Log events
        elif event.type == EventType.ERROR_BURST:
            event.severity = EventSeverity.URGENT
        elif event.type == EventType.NEW_ERROR_PATTERN:
            event.severity = EventSeverity.NOTABLE

        # Security events — always urgent
        elif event.type in (
            EventType.BRUTE_FORCE,
            EventType.SUSPICIOUS_PROCESS,
        ):
            event.severity = EventSeverity.URGENT
        elif event.type == EventType.NEW_OPEN_PORT:
            event.severity = EventSeverity.NOTABLE

        return event

    def _classify_metric(self, event: Event) -> None:
        """Classify a metric event based on threshold rules."""
        data: dict[str, Any] = event.data
        for metric_name, value in data.items():
            if not isinstance(value, (int, float)):
                continue
            rule = self._thresholds.get(metric_name)
            if rule is None:
                continue

            if value >= rule.urgent_threshold:
                event.severity = EventSeverity.URGENT
                event.message = rule.message_template.format(value=value)
                event.type = _metric_to_event_type(metric_name)
                return
            elif value >= rule.notable_threshold:
                event.severity = EventSeverity.NOTABLE
                event.message = rule.message_template.format(value=value)
                event.type = _metric_to_event_type(metric_name)
                return

    def add_threshold(self, rule: ThresholdRule) -> None:
        """Add or replace a threshold rule."""
        self._thresholds[rule.metric] = rule


def _metric_to_event_type(metric: str) -> str:
    """Map a metric name to a specific event type."""
    mapping = {
        "cpu_percent": EventType.CPU_HIGH,
        "memory_percent": EventType.MEMORY_HIGH,
        "disk_percent": EventType.DISK_HIGH,
        "load_per_cpu": EventType.LOAD_HIGH,
    }
    return mapping.get(metric, EventType.METRIC_COLLECTED)
