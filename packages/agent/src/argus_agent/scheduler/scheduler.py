"""Asyncio-based periodic task scheduler."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("argus.scheduler")

TaskFunc = Callable[[], Coroutine[Any, Any, None]]


@dataclass
class ScheduledTask:
    """A periodic task with its schedule."""

    name: str
    func: TaskFunc
    interval_seconds: float
    last_run: datetime | None = None
    run_count: int = 0
    error_count: int = 0
    enabled: bool = True
    _handle: asyncio.Task[None] | None = field(default=None, repr=False)


class Scheduler:
    """Runs periodic tasks as asyncio background tasks.

    Each task runs in its own loop with independent intervals.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False

    def register(
        self,
        name: str,
        func: TaskFunc,
        interval_seconds: float,
        enabled: bool = True,
    ) -> None:
        """Register a periodic task."""
        self._tasks[name] = ScheduledTask(
            name=name,
            func=func,
            interval_seconds=interval_seconds,
            enabled=enabled,
        )

    async def start(self) -> None:
        """Start all enabled scheduled tasks."""
        if self._running:
            return
        self._running = True

        for task in self._tasks.values():
            if task.enabled:
                task._handle = asyncio.create_task(self._run_task(task))

        logger.info(
            "Scheduler started with %d tasks",
            sum(1 for t in self._tasks.values() if t.enabled),
        )

    async def stop(self) -> None:
        """Stop all scheduled tasks."""
        self._running = False
        for task in self._tasks.values():
            if task._handle:
                task._handle.cancel()
                try:
                    await task._handle
                except asyncio.CancelledError:
                    pass
                task._handle = None
        logger.info("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> list[dict[str, Any]]:
        """Get status of all scheduled tasks."""
        return [
            {
                "name": t.name,
                "enabled": t.enabled,
                "interval_seconds": t.interval_seconds,
                "last_run": t.last_run.isoformat() if t.last_run else None,
                "run_count": t.run_count,
                "error_count": t.error_count,
            }
            for t in self._tasks.values()
        ]

    async def _run_task(self, task: ScheduledTask) -> None:
        """Run a single task on its interval."""
        while self._running and task.enabled:
            try:
                await task.func()
                task.last_run = datetime.now(UTC)
                task.run_count += 1
            except Exception:
                task.error_count += 1
                logger.exception("Scheduled task '%s' failed", task.name)

            await asyncio.sleep(task.interval_seconds)
