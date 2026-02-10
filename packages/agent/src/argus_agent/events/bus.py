"""Central event processing hub."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from argus_agent.events.types import Event, EventSeverity

logger = logging.getLogger("argus.events.bus")

# Subscriber callback type
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Central event bus that routes events to subscribers.

    Collectors publish events here. The bus routes to registered handlers
    based on severity or source filters.
    """

    def __init__(self) -> None:
        self._handlers: list[tuple[EventHandler, set[str] | None, set[EventSeverity] | None]] = []
        self._recent_events: list[Event] = []
        self._max_recent = 500

    def subscribe(
        self,
        handler: EventHandler,
        sources: set[str] | None = None,
        severities: set[EventSeverity] | None = None,
    ) -> None:
        """Register a handler for events.

        Args:
            handler: Async callback receiving an Event.
            sources: If set, only deliver events from these sources.
            severities: If set, only deliver events with these severities.
        """
        self._handlers.append((handler, sources, severities))

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers."""
        self._recent_events.append(event)
        if len(self._recent_events) > self._max_recent:
            self._recent_events = self._recent_events[-self._max_recent :]

        if event.severity != EventSeverity.NORMAL:
            logger.info(
                "Event [%s] %s: %s",
                event.severity,
                event.type,
                event.message or "(no message)",
            )

        for handler, sources, severities in self._handlers:
            if sources and event.source not in sources:
                continue
            if severities and event.severity not in severities:
                continue
            try:
                await handler(event)
            except Exception:
                logger.exception("Event handler error for %s", event.type)

    def publish_nowait(self, event: Event) -> None:
        """Schedule event publication without awaiting (for sync contexts)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            logger.warning("No running event loop, dropping event: %s", event.type)

    def get_recent_events(
        self,
        severity: EventSeverity | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> list[Event]:
        """Get recent events, optionally filtered."""
        events = self._recent_events
        if severity:
            events = [e for e in events if e.severity == severity]
        if source:
            events = [e for e in events if e.source == source]
        return events[-limit:]

    def clear(self) -> None:
        """Clear all subscribers and recent events."""
        self._handlers.clear()
        self._recent_events.clear()


# Global singleton
_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global event bus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_event_bus() -> None:
    """Reset the event bus (for testing)."""
    global _bus
    if _bus:
        _bus.clear()
    _bus = None
