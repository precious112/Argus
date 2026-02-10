"""Continuous log file watcher using polling (cross-platform)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from argus_agent.config import get_settings
from argus_agent.events.bus import get_event_bus
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType
from argus_agent.storage.timeseries import insert_log_entry

logger = logging.getLogger("argus.collectors.log_watcher")

# Severity patterns for log line classification
_SEVERITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ERROR", re.compile(r"\b(ERROR|FATAL|CRITICAL|CRIT|EMERG|ALERT)\b", re.IGNORECASE)),
    ("WARNING", re.compile(r"\b(WARNING|WARN)\b", re.IGNORECASE)),
    ("INFO", re.compile(r"\b(INFO|NOTICE)\b", re.IGNORECASE)),
    ("DEBUG", re.compile(r"\bDEBUG\b", re.IGNORECASE)),
]


def _detect_severity(line: str) -> str:
    """Detect log severity from a line of text."""
    for severity, pattern in _SEVERITY_PATTERNS:
        if pattern.search(line):
            return severity
    return ""


class WatchedFile:
    """Tracks state for a single watched log file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset: int = 0
        self.inode: int = 0
        self._init_position()

    def _init_position(self) -> None:
        """Set initial read position to end of file."""
        try:
            stat = self.path.stat()
            self.offset = stat.st_size
            self.inode = stat.st_ino
        except OSError:
            self.offset = 0
            self.inode = 0

    def read_new_lines(self) -> list[tuple[int, str]]:
        """Read new lines since last check. Returns (offset, line) pairs."""
        try:
            stat = self.path.stat()
        except OSError:
            return []

        # File was rotated (different inode or smaller)
        if stat.st_ino != self.inode or stat.st_size < self.offset:
            self.inode = stat.st_ino
            self.offset = 0

        if stat.st_size == self.offset:
            return []

        lines: list[tuple[int, str]] = []
        try:
            with open(self.path, errors="replace") as f:
                f.seek(self.offset)
                while True:
                    line_offset = f.tell()
                    line = f.readline()
                    if not line:
                        break
                    lines.append((line_offset, line.rstrip("\n")))
                self.offset = f.tell()
        except OSError:
            pass

        return lines


class LogWatcher:
    """Watches configured log files for new lines.

    Uses polling (cross-platform). Detects error patterns, indexes metadata
    in DuckDB, emits events to the event bus.
    """

    def __init__(self, poll_interval: float = 2.0) -> None:
        settings = get_settings()
        self._poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._files: dict[str, WatchedFile] = {}
        self._host_root = settings.collector.host_root

        # Error burst detection
        self._error_timestamps: list[float] = []
        self._error_burst_window = 60.0  # seconds
        self._error_burst_threshold = 10
        self._known_error_patterns: set[str] = set()

        # Initialize watched files
        for log_path in settings.collector.log_paths:
            self._add_file(log_path)

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve path with optional host root prefix."""
        if self._host_root and not file_path.startswith(self._host_root):
            return Path(self._host_root) / file_path.lstrip("/")
        return Path(file_path)

    def _add_file(self, path: str) -> None:
        """Add a file to watch if it exists."""
        resolved = self._resolve_path(path)
        if resolved.exists() and resolved.is_file():
            self._files[path] = WatchedFile(resolved)
            logger.info("Watching log file: %s", resolved)
        else:
            logger.debug("Log file not found (will retry): %s", resolved)

    async def start(self) -> None:
        """Start watching log files."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        logger.info("Log watcher started (%d files)", len(self._files))

    async def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Log watcher stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def watched_files(self) -> list[str]:
        return list(self._files.keys())

    async def _watch_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_files()
            except Exception:
                logger.exception("Log watcher poll error")
            await asyncio.sleep(self._poll_interval)

    async def _poll_files(self) -> None:
        """Check all watched files for new lines."""
        bus = get_event_bus()
        now = datetime.now(UTC)

        for file_path, watched in self._files.items():
            new_lines = watched.read_new_lines()
            if not new_lines:
                continue

            for offset, line in new_lines:
                if not line.strip():
                    continue

                severity = _detect_severity(line)

                # Index in DuckDB
                try:
                    insert_log_entry(
                        file_path=file_path,
                        line_offset=offset,
                        severity=severity,
                        message_preview=line[:200],
                        source="log_watcher",
                        timestamp=now,
                    )
                except Exception:
                    pass  # DuckDB write errors shouldn't stop the watcher

                # Track errors for burst detection
                if severity == "ERROR":
                    loop_time = asyncio.get_event_loop().time()
                    self._error_timestamps.append(loop_time)
                    self._error_timestamps = [
                        t
                        for t in self._error_timestamps
                        if loop_time - t < self._error_burst_window
                    ]

                    # Error burst?
                    if len(self._error_timestamps) >= self._error_burst_threshold:
                        await bus.publish(
                            Event(
                                source=EventSource.LOG_WATCHER,
                                type=EventType.ERROR_BURST,
                                severity=EventSeverity.URGENT,
                                message=f"Error burst: {len(self._error_timestamps)} errors "
                                f"in {self._error_burst_window}s from {file_path}",
                                data={
                                    "file": file_path,
                                    "count": len(self._error_timestamps),
                                    "last_error": line[:200],
                                },
                            )
                        )
                        self._error_timestamps.clear()

                    # New error pattern?
                    pattern = _normalize_error(line)
                    if pattern and pattern not in self._known_error_patterns:
                        self._known_error_patterns.add(pattern)
                        await bus.publish(
                            Event(
                                source=EventSource.LOG_WATCHER,
                                type=EventType.NEW_ERROR_PATTERN,
                                severity=EventSeverity.NOTABLE,
                                message=f"New error pattern in {file_path}: {line[:100]}",
                                data={
                                    "file": file_path,
                                    "pattern": pattern,
                                    "line": line[:200],
                                },
                            )
                        )


def _normalize_error(line: str) -> str:
    """Normalize an error line to a pattern (strip timestamps, numbers, etc.)."""
    # Remove timestamps like 2024-01-01 12:00:00
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.\d]*", "<TS>", line)
    # Remove numeric IDs
    normalized = re.sub(r"\b\d{4,}\b", "<N>", normalized)
    # Remove hex hashes
    normalized = re.sub(r"\b[0-9a-f]{8,}\b", "<HEX>", normalized)
    # Remove IPs
    normalized = re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<IP>", normalized)
    return normalized[:100]
