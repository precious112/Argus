"""HTTP client for pushing telemetry to Argus agent."""

from __future__ import annotations

import atexit
import logging
import queue
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from argus.serverless import ServerlessContext

logger = logging.getLogger("argus.sdk")

_DEFAULT_FLUSH_INTERVAL = 5.0
_DEFAULT_BATCH_SIZE = 100
_MAX_RETRIES = 3

# Serverless-tuned defaults
_SERVERLESS_FLUSH_INTERVAL = 1.0
_SERVERLESS_BATCH_SIZE = 10


class ArgusClient:
    """Batched telemetry client. Never blocks the application."""

    def __init__(
        self,
        server_url: str,
        api_key: str = "",
        service_name: str = "",
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._api_key = api_key
        self._service_name = service_name
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._serverless_context: ServerlessContext | None = None

        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10_000)
        self._running = True

        # Background flush thread
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()
        atexit.register(self.close)

    def set_serverless_context(self, ctx: ServerlessContext) -> None:
        """Set the serverless context for event enrichment."""
        self._serverless_context = ctx

    def send_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Queue a telemetry event (non-blocking)."""
        if not self._running:
            return

        event_data = dict(data) if data else {}

        # Enrich with serverless context
        if self._serverless_context:
            ctx_data = self._serverless_context.to_dict()
            # Don't overwrite existing keys
            for k, v in ctx_data.items():
                if k not in event_data:
                    event_data[k] = v

        # Enrich with active invocation ID
        try:
            from argus.serverless import get_active_invocation_id

            inv_id = get_active_invocation_id()
            if inv_id and "invocation_id" not in event_data:
                event_data["invocation_id"] = inv_id
        except ImportError:
            pass

        # Auto-attach trace context if not already present
        try:
            from argus.context import get_current_context

            ctx = get_current_context()
            if ctx:
                if "trace_id" not in event_data:
                    event_data["trace_id"] = ctx.trace_id
                if "span_id" not in event_data:
                    event_data["span_id"] = ctx.span_id
        except ImportError:
            pass

        try:
            self._queue.put_nowait({
                "type": event_type,
                "service": self._service_name,
                "data": event_data,
            })
        except queue.Full:
            logger.warning("Argus SDK event queue full, dropping event")

    def flush_sync(self) -> None:
        """Flush all queued events synchronously.

        Use this in serverless environments where the process may be
        frozen/terminated shortly after the handler returns.
        """
        self._flush()

    def _flush_loop(self) -> None:
        """Background thread: flush events periodically."""
        while self._running:
            time.sleep(self._flush_interval)
            self._flush()
        # Final flush on shutdown
        self._flush()

    def _flush(self) -> None:
        """Send all queued events to Argus."""
        events = []
        while not self._queue.empty() and len(events) < self._batch_size * 10:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not events:
            return

        # Send in batches
        for i in range(0, len(events), self._batch_size):
            batch = events[i : i + self._batch_size]
            self._send_batch(batch)

    def _send_batch(self, events: list[dict[str, Any]]) -> None:
        """POST a batch of events to the ingest endpoint."""
        import httpx

        url = f"{self._server_url}/api/v1/ingest"
        payload = {
            "events": events,
            "sdk": f"argus-python/{_get_version()}",
            "service": self._service_name,
        }
        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-argus-key"] = self._api_key

        for attempt in range(_MAX_RETRIES):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=10)
                if resp.status_code < 400:
                    return
                logger.warning("Argus ingest returned %d", resp.status_code)
            except Exception as e:
                logger.debug("Argus SDK flush attempt %d failed: %s", attempt + 1, e)
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)

        logger.warning("Argus SDK: dropped %d events after %d retries", len(events), _MAX_RETRIES)

    def close(self) -> None:
        """Flush remaining events and stop the background thread."""
        if not self._running:
            return
        self._running = False
        self._thread.join(timeout=5)

    def __enter__(self) -> ArgusClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _get_version() -> str:
    try:
        from argus import __version__
        return __version__
    except ImportError:
        return "0.1.0"
