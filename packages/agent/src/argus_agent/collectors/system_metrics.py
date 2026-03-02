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
    In SaaS mode, metrics are collected via webhooks from the tenant's host.
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
        self._is_saas = settings.deployment.mode == "saas"

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
        logger.info(
            "System metrics collector started (interval=%ds, saas=%s)",
            self._interval, self._is_saas,
        )

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
        if self._is_saas:
            return await self._collect_remote()

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

    async def _collect_remote(self) -> dict[str, float]:
        """SaaS mode: collect metrics via webhooks from tenant hosts."""
        from argus_agent.collectors.remote import execute_remote_tool, get_webhook_tenants

        tenants = await get_webhook_tenants()
        if not tenants:
            logger.debug("No webhook tenants for remote metrics collection")
            return {}

        now = datetime.now(UTC)
        bus = get_event_bus()

        for t in tenants:
            result = await execute_remote_tool(t["tenant_id"], "system_metrics", {})
            if not result:
                continue

            # Map webhook response to metrics dict
            metrics: dict[str, float] = {}
            metrics["cpu_percent"] = float(result.get("cpu_percent", 0))

            mem = result.get("memory", {})
            if isinstance(mem, dict):
                metrics["memory_percent"] = float(mem.get("percent", 0))
                metrics["memory_used_bytes"] = float(mem.get("used_gb", 0)) * 1e9
                metrics["memory_total_bytes"] = float(mem.get("total_gb", 0)) * 1e9

            disk = result.get("disk", {})
            if isinstance(disk, dict):
                metrics["disk_percent"] = float(disk.get("percent", 0))
                metrics["disk_used_bytes"] = float(disk.get("used_gb", 0)) * 1e9
                metrics["disk_total_bytes"] = float(disk.get("total_gb", 0)) * 1e9

            load_avg = result.get("load_avg", [])
            if isinstance(load_avg, list) and len(load_avg) >= 3:
                metrics["load_1m"] = float(load_avg[0])
                metrics["load_5m"] = float(load_avg[1])
                metrics["load_15m"] = float(load_avg[2])

            # Store in metrics repo
            rows = [(now, name, value, None) for name, value in metrics.items()]
            try:
                insert_metrics_batch(rows)
            except Exception:
                logger.exception("Failed to store remote metrics")

            # Emit event
            event = Event(
                source=EventSource.SYSTEM_METRICS,
                type=EventType.METRIC_COLLECTED,
                data={**metrics, "tenant_id": t["tenant_id"]},
            )
            event = self._classifier.classify(event)
            await bus.publish(event)

            # Run anomaly detection
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
                                    "tenant_id": t["tenant_id"],
                                },
                            )
                        )
                except Exception:
                    logger.exception("Anomaly detection error (remote)")

            return metrics

        return {}


# Snapshot for the agent context layer
_latest_snapshot: dict[str, Any] = {}


async def update_system_snapshot() -> dict[str, Any]:
    """Collect a fresh system snapshot for agent context."""
    global _latest_snapshot

    # SaaS mode: use webhook data from first available tenant
    settings = get_settings()
    if settings.deployment.mode == "saas":
        return await _update_snapshot_remote()

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


async def _update_snapshot_remote() -> dict[str, Any]:
    """SaaS mode: get system snapshot from first available tenant webhook."""
    global _latest_snapshot

    from argus_agent.collectors.remote import execute_remote_tool, get_webhook_tenants

    tenants = await get_webhook_tenants()
    if not tenants:
        _latest_snapshot = {"note": "No webhook tenants configured"}
        return _latest_snapshot

    t = tenants[0]
    result = await execute_remote_tool(t["tenant_id"], "system_metrics", {})
    if not result:
        _latest_snapshot = {"note": "Remote metrics unavailable"}
        return _latest_snapshot

    mem = result.get("memory", {})
    disk = result.get("disk", {})
    load_avg = result.get("load_avg", [])

    snapshot: dict[str, Any] = {
        "cpu_percent": result.get("cpu_percent", 0),
        "hostname": result.get("hostname", ""),
        "platform": result.get("platform", ""),
        "memory_percent": mem.get("percent", 0) if isinstance(mem, dict) else 0,
        "memory_used_gb": mem.get("used_gb", 0) if isinstance(mem, dict) else 0,
        "memory_total_gb": mem.get("total_gb", 0) if isinstance(mem, dict) else 0,
        "disk_percent": disk.get("percent", 0) if isinstance(disk, dict) else 0,
        "tenant_id": t["tenant_id"],
    }

    if isinstance(load_avg, list) and len(load_avg) >= 3:
        snapshot["load_avg"] = f"{load_avg[0]:.2f} / {load_avg[1]:.2f} / {load_avg[2]:.2f}"

    # Get top processes
    proc_result = await execute_remote_tool(t["tenant_id"], "process_list", {"limit": 5})
    if proc_result:
        snapshot["top_processes"] = [
            {
                "pid": p.get("pid", 0),
                "name": p.get("name", ""),
                "cpu_percent": p.get("cpu_percent", 0),
                "memory_percent": p.get("memory_percent", 0),
            }
            for p in proc_result.get("processes", [])[:5]
        ]

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
