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


@dataclass
class Event:
    """A system event from any source."""

    source: EventSource
    type: str
    severity: EventSeverity = EventSeverity.NORMAL
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
