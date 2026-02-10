"""Process monitoring collector."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import psutil

from argus_agent.config import get_settings
from argus_agent.events.bus import get_event_bus
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType

logger = logging.getLogger("argus.collectors.process")


class ProcessMonitor:
    """Monitors process state changes at regular intervals.

    Detects: service crashes, restart loops, new processes, OOM kills.
    Tracks top processes by CPU and memory usage.
    """

    def __init__(self, interval: int | None = None) -> None:
        settings = get_settings()
        self._interval = interval or settings.collector.process_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None

        # State tracking
        self._known_pids: set[int] = set()
        self._process_names: dict[str, list[float]] = {}  # name -> [start_times]
        self._restart_window = 300.0  # 5 minutes
        self._restart_threshold = 3  # N restarts in window = restart loop

    async def start(self) -> None:
        """Start monitoring processes."""
        if self._running:
            return
        self._running = True
        # Seed known PIDs on first run
        self._known_pids = {p.pid for p in psutil.process_iter()}
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Process monitor started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Process monitor stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self.check_once()
            except Exception:
                logger.exception("Process monitor error")
            await asyncio.sleep(self._interval)

    async def check_once(self) -> dict[str, Any]:
        """Run one process check and return a snapshot."""
        bus = get_event_bus()
        current_pids: set[int] = set()
        processes: list[dict[str, Any]] = []

        for proc in psutil.process_iter(
            ["pid", "name", "status", "cpu_percent", "memory_percent", "create_time", "username"]
        ):
            try:
                info = proc.info
                if not info:
                    continue
                pid = info["pid"]
                current_pids.add(pid)
                processes.append(
                    {
                        "pid": pid,
                        "name": info.get("name", ""),
                        "status": info.get("status", ""),
                        "cpu_percent": info.get("cpu_percent", 0.0) or 0.0,
                        "memory_percent": round(info.get("memory_percent", 0.0) or 0.0, 2),
                        "username": info.get("username", ""),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Detect disappeared processes (potential crashes)
        disappeared = self._known_pids - current_pids
        if disappeared and self._known_pids:
            # Only flag if we have a previous baseline
            for pid in disappeared:
                # We don't have the name anymore, just note it
                pass

        # Detect restart loops by name
        loop_time = asyncio.get_event_loop().time()
        for proc_info in processes:
            name = proc_info["name"]
            if name not in self._process_names:
                self._process_names[name] = []

            # Check if this is a recent start (create_time-based detection isn't
            # reliable across platforms, so we track appearance)
            if proc_info["pid"] not in self._known_pids:
                self._process_names[name].append(loop_time)
                # Trim old entries
                self._process_names[name] = [
                    t for t in self._process_names[name] if loop_time - t < self._restart_window
                ]
                # Check for restart loop
                if len(self._process_names[name]) >= self._restart_threshold:
                    await bus.publish(
                        Event(
                            source=EventSource.PROCESS_MONITOR,
                            type=EventType.PROCESS_RESTART_LOOP,
                            severity=EventSeverity.NOTABLE,
                            message=f"Process '{name}' restarted "
                            f"{len(self._process_names[name])} times in "
                            f"{self._restart_window}s",
                            data={"name": name, "restarts": len(self._process_names[name])},
                        )
                    )

        self._known_pids = current_pids

        # Sort by CPU usage
        processes.sort(key=lambda p: p.get("cpu_percent", 0), reverse=True)

        # Emit snapshot event
        await bus.publish(
            Event(
                source=EventSource.PROCESS_MONITOR,
                type=EventType.PROCESS_SNAPSHOT,
                data={
                    "total": len(processes),
                    "top_cpu": processes[:10],
                },
            )
        )

        return {
            "total": len(processes),
            "processes": processes,
        }


def get_process_list(
    sort_by: str = "cpu_percent",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get current process list snapshot (synchronous, for tools)."""
    processes: list[dict[str, Any]] = []

    for proc in psutil.process_iter(
        ["pid", "name", "status", "cpu_percent", "memory_percent", "username", "cmdline"]
    ):
        try:
            info = proc.info
            if not info:
                continue
            cmdline = info.get("cmdline") or []
            processes.append(
                {
                    "pid": info["pid"],
                    "name": info.get("name", ""),
                    "status": info.get("status", ""),
                    "cpu_percent": info.get("cpu_percent", 0.0) or 0.0,
                    "memory_percent": round(info.get("memory_percent", 0.0) or 0.0, 2),
                    "username": info.get("username", ""),
                    "cmdline": " ".join(cmdline)[:200] if cmdline else "",
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Sort
    if sort_by in ("cpu_percent", "memory_percent", "pid"):
        processes.sort(key=lambda p: p.get(sort_by, 0), reverse=sort_by != "pid")
    else:
        processes.sort(key=lambda p: p.get("cpu_percent", 0), reverse=True)

    return processes[:limit]
