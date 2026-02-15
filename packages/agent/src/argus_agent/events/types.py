"""Event type definitions for the event bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EventSeverity(StrEnum):
    NORMAL = "NORMAL"
    NOTABLE = "NOTABLE"
    URGENT = "URGENT"


class EventSource(StrEnum):
    LOG_WATCHER = "log_watcher"
    SYSTEM_METRICS = "system_metrics"
    PROCESS_MONITOR = "process_monitor"
    SECURITY_SCANNER = "security_scanner"
    SDK_TELEMETRY = "sdk_telemetry"
    SCHEDULER = "scheduler"


class EventType(StrEnum):
    """Well-known event types emitted by collectors."""

    # System metrics events
    METRIC_COLLECTED = "metric_collected"
    CPU_HIGH = "cpu_high"
    MEMORY_HIGH = "memory_high"
    DISK_HIGH = "disk_high"
    LOAD_HIGH = "load_high"
    RESOURCE_CRITICAL = "resource_critical"
    RAPID_DEGRADATION = "rapid_degradation"

    # Process events
    PROCESS_SNAPSHOT = "process_snapshot"
    PROCESS_CRASHED = "process_crashed"
    PROCESS_OOM_KILLED = "process_oom_killed"
    PROCESS_RESTART_LOOP = "process_restart_loop"
    NEW_PROCESS = "new_process"

    # Log events
    LOG_LINE = "log_line"
    ERROR_BURST = "error_burst"
    NEW_ERROR_PATTERN = "new_error_pattern"

    # Security events
    BRUTE_FORCE = "brute_force"
    NEW_OPEN_PORT = "new_open_port"
    SUSPICIOUS_PROCESS = "suspicious_process"
    NEW_EXECUTABLE = "new_executable"
    PERMISSION_RISK = "permission_risk"
    SUSPICIOUS_OUTBOUND = "suspicious_outbound"

    # Anomaly events
    ANOMALY_DETECTED = "anomaly_detected"

    # SDK telemetry events
    SDK_ERROR_SPIKE = "sdk_error_spike"
    SDK_LATENCY_DEGRADATION = "sdk_latency_degradation"
    SDK_COLD_START_SPIKE = "sdk_cold_start_spike"
    SDK_SERVICE_SILENT = "sdk_service_silent"

    # Scheduler events
    HEALTH_CHECK = "health_check"
    TREND_ANALYSIS = "trend_analysis"


@dataclass
class Event:
    """A system event from any source."""

    source: EventSource
    type: str
    severity: EventSeverity = EventSeverity.NORMAL
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
