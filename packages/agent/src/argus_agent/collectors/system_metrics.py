"""System metrics collector using psutil."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

import psutil

from argus_agent.config import get_settings
from argus_agent.events.bus import get_event_bus
from argus_agent.events.classifier import EventClassifier
from argus_agent.events.types import Event, EventSource, EventType
from argus_agent.storage.timeseries import insert_metrics_batch

logger = logging.getLogger("argus.collectors.metrics")


class SystemMetricsCollector:
    """Collects system metrics (CPU, memory, disk, network) at regular intervals.

    Stores data in DuckDB and emits events to the event bus for classification.
    """

    def __init__(self, interval: int | None = None) -> None:
        settings = get_settings()
        self._interval = interval or settings.collector.metrics_interval
        self._host_root = settings.collector.host_root
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._classifier = EventClassifier()
        self._last_net_io: Any = None
        self._last_disk_io: Any = None
        self._last_collect_time: float | None = None
        self.anomaly_detector: Any = None  # Set externally (AnomalyDetector)

    async def start(self) -> None:
        """Start collecting metrics in background."""
        if self._running:
            return
        self._running = True
        # Set PROC path for psutil when running in a container
        if self._host_root:
            proc_path = os.path.join(self._host_root, "proc")
            if os.path.isdir(proc_path):
                os.environ["PSUTIL_PROC_PATH"] = proc_path
        self._task = asyncio.create_task(self._collect_loop())
        logger.info("System metrics collector started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop collecting metrics."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("System metrics collector stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _collect_loop(self) -> None:
        """Main collection loop."""
        while self._running:
            try:
                await self.collect_once()
            except Exception:
                logger.exception("Metrics collection error")
            await asyncio.sleep(self._interval)

    async def collect_once(self) -> dict[str, float]:
        """Collect all metrics once and return them as a dict."""
        now = datetime.now(UTC)
        metrics: dict[str, float] = {}

        # CPU
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count() or 1
        metrics["cpu_percent"] = cpu_percent
        metrics["cpu_count"] = float(cpu_count)

        # Load average
        try:
            load1, load5, load15 = os.getloadavg()
            metrics["load_1m"] = load1
            metrics["load_5m"] = load5
            metrics["load_15m"] = load15
            metrics["load_per_cpu"] = load1 / cpu_count
        except OSError:
            pass

        # Memory
        mem = psutil.virtual_memory()
        metrics["memory_percent"] = mem.percent
        metrics["memory_used_bytes"] = float(mem.used)
        metrics["memory_total_bytes"] = float(mem.total)
        metrics["memory_available_bytes"] = float(mem.available)

        # Swap
        swap = psutil.swap_memory()
        metrics["swap_percent"] = swap.percent
        metrics["swap_used_bytes"] = float(swap.used)

        # Disk
        try:
            disk = psutil.disk_usage("/")
            metrics["disk_percent"] = disk.percent
            metrics["disk_used_bytes"] = float(disk.used)
            metrics["disk_total_bytes"] = float(disk.total)
            metrics["disk_free_bytes"] = float(disk.free)
        except OSError:
            pass

        # Network I/O rates
        try:
            net_io = psutil.net_io_counters()
            current_time = asyncio.get_event_loop().time()
            if self._last_net_io and self._last_collect_time:
                dt = current_time - self._last_collect_time
                if dt > 0:
                    metrics["net_bytes_sent_per_sec"] = (
                        net_io.bytes_sent - self._last_net_io.bytes_sent
                    ) / dt
                    metrics["net_bytes_recv_per_sec"] = (
                        net_io.bytes_recv - self._last_net_io.bytes_recv
                    ) / dt
            self._last_net_io = net_io
            self._last_collect_time = current_time
        except Exception:
            pass

        # Store in DuckDB
        rows = [(now, name, value, None) for name, value in metrics.items()]
        try:
            insert_metrics_batch(rows)
        except Exception:
            logger.exception("Failed to store metrics in DuckDB")

        # Emit event for classification
        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            data=metrics,
        )
        event = self._classifier.classify(event)
        bus = get_event_bus()
        await bus.publish(event)

        # Run anomaly detection if configured
        if self.anomaly_detector is not None:
            try:
                anomalies = self.anomaly_detector.check_all_current(metrics)
                for anomaly in anomalies:
                    await bus.publish(
                        Event(
                            source=EventSource.SYSTEM_METRICS,
                            type=EventType.ANOMALY_DETECTED,
                            severity=anomaly.severity,
                            message=anomaly.message,
                            data={
                                "metric": anomaly.metric_name,
                                "value": anomaly.value,
                                "mean": anomaly.baseline_mean,
                                "z_score": anomaly.z_score,
                            },
                        )
                    )
            except Exception:
                logger.exception("Anomaly detection error")

        return metrics


# Snapshot for the agent context layer
_latest_snapshot: dict[str, Any] = {}


async def update_system_snapshot() -> dict[str, Any]:
    """Collect a fresh system snapshot for agent context."""
    global _latest_snapshot

    cpu_count = psutil.cpu_count() or 1
    mem = psutil.virtual_memory()

    snapshot: dict[str, Any] = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": cpu_count,
        "memory_percent": mem.percent,
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_total_gb": round(mem.total / (1024**3), 1),
    }

    try:
        load1, load5, load15 = os.getloadavg()
        snapshot["load_avg"] = f"{load1:.2f} / {load5:.2f} / {load15:.2f}"
    except OSError:
        pass

    try:
        disk = psutil.disk_usage("/")
        snapshot["disk_percent"] = disk.percent
        snapshot["disk_free_gb"] = round(disk.free / (1024**3), 1)
    except OSError:
        pass

    # Top 5 processes by CPU
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "username"]):
            info = p.info
            if info and info.get("cpu_percent", 0):
                procs.append(info)
        procs.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
        snapshot["top_processes"] = [
            {
                "pid": p.get("pid", 0),
                "name": p.get("name", ""),
                "cpu_percent": p.get("cpu_percent", 0),
                "memory_percent": p.get("memory_percent", 0),
                "username": p.get("username", ""),
            }
            for p in procs[:5]
        ]
    except Exception:
        pass

    _latest_snapshot = snapshot
    return snapshot


def get_system_snapshot() -> dict[str, Any]:
    """Get the most recent system snapshot (non-async)."""
    return _latest_snapshot


def format_snapshot_for_prompt(snapshot: dict[str, Any] | None = None) -> str:
    """Format system snapshot as text for the agent system prompt."""
    s = snapshot or _latest_snapshot
    if not s:
        return "System metrics not yet collected."

    lines = [
        f"- CPU: {s.get('cpu_percent', '?')}% ({s.get('cpu_count', '?')} cores)",
        f"- Memory: {s.get('memory_percent', '?')}% "
        f"({s.get('memory_used_gb', '?')}/{s.get('memory_total_gb', '?')} GB)",
    ]
    if "disk_percent" in s:
        lines.append(f"- Disk: {s['disk_percent']}% used ({s.get('disk_free_gb', '?')} GB free)")
    if "load_avg" in s:
        lines.append(f"- Load average: {s['load_avg']}")
    if "top_processes" in s:
        lines.append("- Top processes:")
        for p in s["top_processes"]:
            if isinstance(p, dict):
                lines.append(
                    f"  - {p.get('name', '?')} (PID {p.get('pid', '?')}): "
                    f"CPU {p.get('cpu_percent', 0):.1f}%, "
                    f"MEM {p.get('memory_percent', 0):.1f}%"
                )
            else:
                lines.append(f"  - {p}")

    return "\n".join(lines)
