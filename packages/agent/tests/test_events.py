"""Tests for event bus and classifier."""

from __future__ import annotations

import pytest

from argus_agent.config import reset_settings
from argus_agent.events.bus import EventBus, get_event_bus, reset_event_bus
from argus_agent.events.classifier import EventClassifier, ThresholdRule
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    reset_event_bus()
    yield
    reset_settings()
    reset_event_bus()


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self):
        bus = EventBus()
        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(handler)

        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            message="test",
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].message == "test"

    @pytest.mark.asyncio
    async def test_source_filter(self):
        bus = EventBus()
        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(handler, sources={EventSource.LOG_WATCHER})

        await bus.publish(Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
        ))
        await bus.publish(Event(
            source=EventSource.LOG_WATCHER,
            type=EventType.LOG_LINE,
        ))

        assert len(received) == 1
        assert received[0].source == EventSource.LOG_WATCHER

    @pytest.mark.asyncio
    async def test_severity_filter(self):
        bus = EventBus()
        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(handler, severities={EventSeverity.URGENT})

        await bus.publish(Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            severity=EventSeverity.NORMAL,
        ))
        await bus.publish(Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.CPU_HIGH,
            severity=EventSeverity.URGENT,
        ))

        assert len(received) == 1
        assert received[0].severity == EventSeverity.URGENT

    @pytest.mark.asyncio
    async def test_recent_events(self):
        bus = EventBus()
        for i in range(5):
            await bus.publish(Event(
                source=EventSource.SYSTEM_METRICS,
                type=EventType.METRIC_COLLECTED,
                message=f"event-{i}",
            ))

        recent = bus.get_recent_events(limit=3)
        assert len(recent) == 3
        assert recent[-1].message == "event-4"

    @pytest.mark.asyncio
    async def test_handler_error_doesnt_break_bus(self):
        bus = EventBus()
        called = []

        async def bad_handler(event: Event):
            raise ValueError("oops")

        async def good_handler(event: Event):
            called.append(event)

        bus.subscribe(bad_handler)
        bus.subscribe(good_handler)

        await bus.publish(Event(
            source=EventSource.SCHEDULER,
            type=EventType.HEALTH_CHECK,
        ))

        assert len(called) == 1

    def test_get_event_bus_singleton(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_clear(self):
        bus = EventBus()
        bus.subscribe(lambda e: None)  # type: ignore
        bus.clear()
        assert len(bus._handlers) == 0


class TestEventClassifier:
    def test_normal_metric(self):
        classifier = EventClassifier()
        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            data={"cpu_percent": 30.0},
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.NORMAL

    def test_notable_cpu(self):
        classifier = EventClassifier()
        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            data={"cpu_percent": 85.0},
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.NOTABLE
        assert result.type == EventType.CPU_HIGH

    def test_urgent_cpu(self):
        classifier = EventClassifier()
        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            data={"cpu_percent": 96.0},
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.URGENT

    def test_memory_thresholds(self):
        classifier = EventClassifier()
        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            data={"memory_percent": 96.0},
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.URGENT
        assert result.type == EventType.MEMORY_HIGH

    def test_process_crashed_is_urgent(self):
        classifier = EventClassifier()
        event = Event(
            source=EventSource.PROCESS_MONITOR,
            type=EventType.PROCESS_CRASHED,
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.URGENT

    def test_error_burst_is_urgent(self):
        classifier = EventClassifier()
        event = Event(
            source=EventSource.LOG_WATCHER,
            type=EventType.ERROR_BURST,
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.URGENT

    def test_new_error_pattern_is_notable(self):
        classifier = EventClassifier()
        event = Event(
            source=EventSource.LOG_WATCHER,
            type=EventType.NEW_ERROR_PATTERN,
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.NOTABLE

    def test_preserves_pre_classified(self):
        classifier = EventClassifier()
        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            severity=EventSeverity.URGENT,
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.URGENT

    def test_custom_threshold(self):
        classifier = EventClassifier()
        classifier.add_threshold(ThresholdRule(
            metric="cpu_percent",
            notable_threshold=50.0,
            urgent_threshold=70.0,
            message_template="CPU at {value:.1f}%",
        ))
        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            data={"cpu_percent": 55.0},
        )
        result = classifier.classify(event)
        assert result.severity == EventSeverity.NOTABLE
