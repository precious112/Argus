"""Argus Python SDK - Instrumentation for AI-native observability."""

from __future__ import annotations

from typing import Any

__version__ = "0.1.0"

_client = None


def init(
    server_url: str = "http://localhost:7600",
    api_key: str = "",
    service_name: str = "",
    flush_interval: float = 5.0,
    batch_size: int = 100,
) -> None:
    """Initialize the Argus SDK. Must be called before other methods."""
    global _client
    from argus.client import ArgusClient

    _client = ArgusClient(
        server_url=server_url,
        api_key=api_key,
        service_name=service_name,
        flush_interval=flush_interval,
        batch_size=batch_size,
    )


def event(name: str, data: dict[str, Any] | None = None) -> None:
    """Send a custom event."""
    if _client is None:
        return
    _client.send_event("event", {"name": name, **(data or {})})


def capture_exception(exc: BaseException | None = None) -> None:
    """Capture an exception with traceback."""
    import sys
    import traceback

    if exc is None:
        exc = sys.exc_info()[1]
    if exc is None:
        return
    if _client is None:
        return

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _client.send_event("exception", {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": tb,
    })


def shutdown() -> None:
    """Flush and close the SDK client."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
