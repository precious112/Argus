"""Persistent heartbeat monitor for SDK services.

Seeds known services from the database on first run so it survives restarts.
Every interval, checks which previously-active services have gone silent and
emits SDK_SERVICE_SILENT / SDK_SERVICE_RECOVERED events.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from argus_agent.events.bus import get_event_bus
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType

logger = logging.getLogger("argus.collectors.heartbeat")

# How long a service can be silent before we alert (seconds)
DEFAULT_SILENCE_THRESHOLD = 300  # 5 minutes
# How far back to seed known services on first boot
SEED_WINDOW_MINUTES = 1440  # 24 hours


class HeartbeatMonitor:
    """Monitors SDK service liveness using DB-backed state."""

    def __init__(
        self,
        interval: int = 60,
        silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
    ) -> None:
        self._interval = interval
        self._silence_threshold = silence_threshold
        self._running = False
        self._task: asyncio.Task[None] | None = None
        # service → last-seen timestamp
        self._known_services: dict[str, datetime] = {}
        # services currently in "silent" state
        self._silent_services: set[str] = set()
        self._seeded = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Heartbeat monitor started (interval=%ds, silence=%ds)",
            self._interval,
            self._silence_threshold,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Heartbeat monitor stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check()
            except Exception:
                logger.exception("Heartbeat check error")
            await asyncio.sleep(self._interval)

    async def _check(self) -> None:
        try:
            from argus_agent.storage.timeseries import query_service_summary
        except RuntimeError:
            return  # Storage not initialized yet

        # Seed from a wide window on first run so we know about services
        # that reported before the last restart.
        if not self._seeded:
            await self._seed(query_service_summary)
            self._seeded = True
            return  # skip alerting on the very first tick

        # Query recent activity (match the silence threshold window)
        try:
            since_minutes = max(1, self._silence_threshold // 60)
            summaries = query_service_summary(since_minutes=since_minutes)
        except Exception:
            return

        now = datetime.now(UTC).replace(tzinfo=None)
        active_services = {s["service"] for s in summaries if s.get("invocation_count", 0) > 0}
        bus = get_event_bus()

        # Update last-seen for active services
        for svc in active_services:
            self._known_services[svc] = now

        # Check for recovered services
        newly_recovered = self._silent_services & active_services
        for svc in newly_recovered:
            self._silent_services.discard(svc)
            await bus.publish(Event(
                source=EventSource.SDK_TELEMETRY,
                type=EventType.SDK_SERVICE_RECOVERED,
                severity=EventSeverity.NOTABLE,
                message=f"Service '{svc}' has resumed sending telemetry",
                data={"service": svc},
            ))
            logger.info("Service '%s' recovered", svc)

        # Check for newly silent services
        threshold = timedelta(seconds=self._silence_threshold)
        for svc, last_seen in list(self._known_services.items()):
            if svc in active_services:
                continue
            if svc in self._silent_services:
                continue  # already alerted
            if now - last_seen > threshold:
                self._silent_services.add(svc)
                await bus.publish(Event(
                    source=EventSource.SDK_TELEMETRY,
                    type=EventType.SDK_SERVICE_SILENT,
                    severity=EventSeverity.NOTABLE,
                    message=f"Service '{svc}' has stopped sending telemetry",
                    data={"service": svc},
                ))
                logger.info("Service '%s' went silent", svc)

    async def _seed(self, query_fn: object) -> None:
        """Seed known services from the DB using a wide window."""
        try:
            summaries = query_fn(since_minutes=SEED_WINDOW_MINUTES)  # type: ignore[operator]
        except Exception:
            logger.debug("Could not seed heartbeat services from DB", exc_info=True)
            return

        now = datetime.now(UTC).replace(tzinfo=None)
        for s in summaries:
            svc = s["service"]
            self._known_services[svc] = now
        logger.info("Heartbeat seeded %d services from DB", len(self._known_services))
