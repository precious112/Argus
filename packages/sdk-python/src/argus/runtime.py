"""Runtime metrics collector for Python applications."""

from __future__ import annotations

import gc
import logging
import resource
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argus.client import ArgusClient

logger = logging.getLogger("argus.runtime")


class RuntimeMetricsCollector:
    """Daemon thread that periodically collects Python runtime metrics."""

    def __init__(self, client: ArgusClient, interval: float = 30.0) -> None:
        self._client = client
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._collect_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _collect_loop(self) -> None:
        while self._running:
            try:
                self._collect()
            except Exception:
                logger.debug("Runtime metrics collection error", exc_info=True)
            time.sleep(self._interval)

    def _collect(self) -> None:
        # Memory via resource.getrusage
        usage = resource.getrusage(resource.RUSAGE_SELF)
        # maxrss is in bytes on Linux, KB on macOS
        rss = usage.ru_maxrss
        self._send("process_rss_bytes", float(rss))

        # GC stats
        gc_counts = gc.get_count()
        self._send("gc_collections_gen0", float(gc_counts[0]))
        self._send("gc_collections_gen1", float(gc_counts[1]))
        self._send("gc_collections_gen2", float(gc_counts[2]))

        # Tracked objects
        tracked = len(gc.get_objects())
        self._send("gc_objects_tracked", float(tracked))

        # Thread count
        self._send("thread_count", float(threading.active_count()))

    def _send(self, metric_name: str, value: float) -> None:
        self._client.send_event("runtime_metric", {
            "metric_name": metric_name,
            "value": value,
        })
