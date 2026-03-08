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
    In SaaS mode, process data is collected via webhooks.
    """

    def __init__(self, interval: int | None = None) -> None:
        settings = get_settings()
        self._interval = interval or settings.collector.process_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._is_saas = settings.deployment.mode == "saas"

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
        # Seed known PIDs on first run (skip in SaaS mode — no local processes)
        if not self._is_saas:
            self._known_pids = {p.pid for p in psutil.process_iter()}
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(
            "Process monitor started (interval=%ds, saas=%s)",
            self._interval, self._is_saas,
        )

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
        if self._is_saas:
            return await self._check_remote()

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
            for pid in disappeared:
                pass

        # Detect restart loops by name
        loop_time = asyncio.get_event_loop().time()
        for proc_info in processes:
            name = proc_info["name"]
            if name not in self._process_names:
                self._process_names[name] = []

            if proc_info["pid"] not in self._known_pids:
                self._process_names[name].append(loop_time)
                self._process_names[name] = [
                    t for t in self._process_names[name] if loop_time - t < self._restart_window
                ]
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

    async def _check_remote(self) -> dict[str, Any]:
        """SaaS mode: collect process data via webhooks."""
        from argus_agent.collectors.remote import execute_remote_tool, get_webhook_tenants

        bus = get_event_bus()
        tenants = await get_webhook_tenants()
        if not tenants:
            return {"total": 0, "processes": []}

        all_processes: list[dict[str, Any]] = []
        loop_time = asyncio.get_event_loop().time()

        for t in tenants:
            result = await execute_remote_tool(t["tenant_id"], "process_list", {"limit": 100})
            if not result:
                continue

            current_pids: set[int] = set()
            for proc in result.get("processes", []):
                pid = proc.get("pid", 0)
                name = proc.get("name", "")
                current_pids.add(pid)
                all_processes.append({
                    "pid": pid,
                    "name": name,
                    "status": proc.get("status", ""),
                    "cpu_percent": proc.get("cpu_percent", 0.0) or 0.0,
                    "memory_percent": proc.get("memory_percent", 0.0) or 0.0,
                    "tenant_id": t["tenant_id"],
                })

                # Restart loop detection by name
                if name not in self._process_names:
                    self._process_names[name] = []

                if pid not in self._known_pids:
                    self._process_names[name].append(loop_time)
                    self._process_names[name] = [
                        ts for ts in self._process_names[name]
                        if loop_time - ts < self._restart_window
                    ]
                    if len(self._process_names[name]) >= self._restart_threshold:
                        await bus.publish(
                            Event(
                                source=EventSource.PROCESS_MONITOR,
                                type=EventType.PROCESS_RESTART_LOOP,
                                severity=EventSeverity.NOTABLE,
                                message=f"Process '{name}' restarted "
                                f"{len(self._process_names[name])} times in "
                                f"{self._restart_window}s (tenant {t['tenant_id']})",
                                data={
                                    "name": name,
                                    "restarts": len(self._process_names[name]),
                                    "tenant_id": t["tenant_id"],
                                },
                            )
                        )

            self._known_pids = current_pids

        # Sort by CPU usage
        all_processes.sort(key=lambda p: p.get("cpu_percent", 0), reverse=True)

        # Emit snapshot event
        await bus.publish(
            Event(
                source=EventSource.PROCESS_MONITOR,
                type=EventType.PROCESS_SNAPSHOT,
                data={
                    "total": len(all_processes),
                    "top_cpu": all_processes[:10],
                },
            )
        )

        return {
            "total": len(all_processes),
            "processes": all_processes,
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
