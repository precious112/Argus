"""Built-in periodic tasks (Tier 1 and Tier 2)."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import psutil

from argus_agent.events.bus import get_event_bus
from argus_agent.events.classifier import EventClassifier
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType
from argus_agent.storage.repositories import get_metrics_repository

logger = logging.getLogger("argus.scheduler.tasks")

_classifier = EventClassifier()


async def quick_health_check() -> None:
    """Tier 1: Quick threshold checks (every 5 min).

    Zero LLM cost. Checks CPU, memory, disk, and load against thresholds.
    Emits events for anything abnormal.
    """
    from argus_agent.config import get_settings
    if get_settings().deployment.mode == "saas":
        await _remote_health_check()
        return

    bus = get_event_bus()
    findings: list[str] = []

    # CPU
    cpu = psutil.cpu_percent(interval=1)
    if cpu > 95:
        findings.append(f"CRITICAL: CPU at {cpu}%")
    elif cpu > 80:
        findings.append(f"WARNING: CPU at {cpu}%")

    # Memory
    mem = psutil.virtual_memory()
    if mem.percent > 95:
        findings.append(f"CRITICAL: Memory at {mem.percent}%")
    elif mem.percent > 85:
        findings.append(f"WARNING: Memory at {mem.percent}%")

    # Disk
    try:
        disk = psutil.disk_usage("/")
        if disk.percent > 95:
            findings.append(f"CRITICAL: Disk at {disk.percent}%")
        elif disk.percent > 85:
            findings.append(f"WARNING: Disk at {disk.percent}%")
    except OSError:
        pass

    # Load
    try:
        load1, _, _ = os.getloadavg()
        cpu_count = psutil.cpu_count() or 1
        load_per_cpu = load1 / cpu_count
        if load_per_cpu > 3.0:
            findings.append(f"CRITICAL: Load per CPU at {load_per_cpu:.2f}")
        elif load_per_cpu > 1.5:
            findings.append(f"WARNING: Load per CPU at {load_per_cpu:.2f}")
    except OSError:
        pass

    # Emit event if anything is wrong
    if findings:
        severity = (
            EventSeverity.URGENT
            if any("CRITICAL" in f for f in findings)
            else EventSeverity.NOTABLE
        )
        await bus.publish(
            Event(
                source=EventSource.SCHEDULER,
                type=EventType.HEALTH_CHECK,
                severity=severity,
                message="; ".join(findings),
                data={"findings": findings},
            )
        )
    else:
        await bus.publish(
            Event(
                source=EventSource.SCHEDULER,
                type=EventType.HEALTH_CHECK,
                message="All systems normal",
            )
        )


async def _remote_health_check() -> None:
    """SaaS mode: health check via webhooks to tenant hosts."""
    from argus_agent.collectors.remote import execute_remote_tool, get_webhook_tenants

    bus = get_event_bus()
    tenants = await get_webhook_tenants()
    if not tenants:
        await bus.publish(
            Event(
                source=EventSource.SCHEDULER,
                type=EventType.HEALTH_CHECK,
                message="No webhook tenants configured",
            )
        )
        return

    for t in tenants:
        findings: list[str] = []
        result = await execute_remote_tool(t["tenant_id"], "system_metrics", {})
        if not result:
            findings.append(f"WARNING: Could not reach tenant {t['tenant_id']}")
        else:
            cpu = result.get("cpu_percent", 0)
            if cpu > 95:
                findings.append(f"CRITICAL: CPU at {cpu}%")
            elif cpu > 80:
                findings.append(f"WARNING: CPU at {cpu}%")

            mem = result.get("memory", {})
            mem_pct = mem.get("percent", 0) if isinstance(mem, dict) else 0
            if mem_pct > 95:
                findings.append(f"CRITICAL: Memory at {mem_pct}%")
            elif mem_pct > 85:
                findings.append(f"WARNING: Memory at {mem_pct}%")

            disk = result.get("disk", {})
            disk_pct = disk.get("percent", 0) if isinstance(disk, dict) else 0
            if disk_pct > 95:
                findings.append(f"CRITICAL: Disk at {disk_pct}%")
            elif disk_pct > 85:
                findings.append(f"WARNING: Disk at {disk_pct}%")

            load_avg = result.get("load_avg", [])
            if isinstance(load_avg, list) and load_avg:
                load1 = float(load_avg[0])
                # Estimate CPU count from memory/disk presence (assume at least 1)
                load_per_cpu = load1
                if load_per_cpu > 3.0:
                    findings.append(f"CRITICAL: Load at {load1:.2f}")
                elif load_per_cpu > 1.5:
                    findings.append(f"WARNING: Load at {load1:.2f}")

        if findings:
            severity = (
                EventSeverity.URGENT
                if any("CRITICAL" in f for f in findings)
                else EventSeverity.NOTABLE
            )
            await bus.publish(
                Event(
                    source=EventSource.SCHEDULER,
                    type=EventType.HEALTH_CHECK,
                    severity=severity,
                    message=f"[tenant {t['tenant_id']}] " + "; ".join(findings),
                    data={"findings": findings, "tenant_id": t["tenant_id"]},
                )
            )
        else:
            await bus.publish(
                Event(
                    source=EventSource.SCHEDULER,
                    type=EventType.HEALTH_CHECK,
                    message=f"[tenant {t['tenant_id']}] All systems normal",
                    data={"tenant_id": t["tenant_id"]},
                )
            )


async def trend_analysis() -> None:
    """Tier 2: Statistical trend analysis (every 30 min).

    Zero LLM cost. Compares recent metrics to 24h averages to detect
    degradation trends.
    """
    bus = get_event_bus()
    now = datetime.now(UTC)
    findings: list[dict[str, Any]] = []
    repo = get_metrics_repository()

    key_metrics = ["cpu_percent", "memory_percent", "disk_percent"]
    for metric_name in key_metrics:
        # 24h baseline
        baseline = repo.query_metrics_summary(metric_name, since=now - timedelta(hours=24))
        # Last 30 min
        recent = repo.query_metrics_summary(metric_name, since=now - timedelta(minutes=30))

        if baseline.get("count", 0) < 10 or recent.get("count", 0) < 2:
            continue

        baseline_avg = baseline.get("avg", 0)
        recent_avg = recent.get("avg", 0)

        if baseline_avg == 0:
            continue

        # Check for significant increase (>30% above baseline)
        pct_change = ((recent_avg - baseline_avg) / baseline_avg) * 100
        if pct_change > 30:
            findings.append(
                {
                    "metric": metric_name,
                    "baseline_avg": round(baseline_avg, 1),
                    "recent_avg": round(recent_avg, 1),
                    "pct_change": round(pct_change, 1),
                }
            )

    # Check for rapid disk usage growth
    disk_data = repo.query_metrics(
        "disk_percent",
        since=now - timedelta(hours=6),
        limit=500,
    )
    if len(disk_data) >= 10:
        first_val = disk_data[-1]["value"]  # oldest (data is DESC)
        last_val = disk_data[0]["value"]  # newest
        if last_val - first_val > 5:  # >5% growth in 6h
            findings.append(
                {
                    "metric": "disk_growth",
                    "message": f"Disk grew {last_val - first_val:.1f}% in last 6 hours",
                    "current": round(last_val, 1),
                }
            )

    if findings:
        await bus.publish(
            Event(
                source=EventSource.SCHEDULER,
                type=EventType.TREND_ANALYSIS,
                severity=EventSeverity.NOTABLE,
                message=f"Trend analysis found {len(findings)} concern(s)",
                data={"findings": findings},
            )
        )
    else:
        await bus.publish(
            Event(
                source=EventSource.SCHEDULER,
                type=EventType.TREND_ANALYSIS,
                message="No concerning trends detected",
            )
        )


async def quick_security_check() -> None:
    """Tier 1: Quick security scan (every 5 min).

    Zero LLM cost. Runs a lightweight security scan and emits events.
    """
    try:
        from argus_agent.main import _get_security_scanner

        scanner = _get_security_scanner()
        if scanner:
            await scanner.scan_once()
    except Exception:
        logger.exception("Quick security check failed")
