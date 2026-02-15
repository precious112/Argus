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
    from argus.client import ArgusClient, _SERVERLESS_BATCH_SIZE, _SERVERLESS_FLUSH_INTERVAL
    from argus.serverless import _build_context, detect_runtime

    # Auto-detect serverless runtime
    runtime = detect_runtime()
    if runtime:
        # Use serverless-tuned defaults unless explicitly overridden
        if flush_interval == 5.0:
            flush_interval = _SERVERLESS_FLUSH_INTERVAL
        if batch_size == 100:
            batch_size = _SERVERLESS_BATCH_SIZE

    _client = ArgusClient(
        server_url=server_url,
        api_key=api_key,
        service_name=service_name,
        flush_interval=flush_interval,
        batch_size=batch_size,
    )

    # Set serverless context if detected
    if runtime:
        ctx = _build_context(runtime)
        if service_name:
            ctx.function_name = ctx.function_name or service_name
        _client.set_serverless_context(ctx)


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


def start_invocation(
    function_name: str = "",
    invocation_id: str = "",
) -> str:
    """Start tracking a serverless invocation. Returns invocation_id."""
    from argus.serverless import start_invocation as _start

    return _start(function_name=function_name, invocation_id=invocation_id)


def end_invocation(status: str = "ok", error: str = "") -> None:
    """End tracking the current serverless invocation."""
    from argus.serverless import end_invocation as _end

    _end(status=status, error=error)


def flush_sync() -> None:
    """Flush all queued events synchronously."""
    if _client is not None:
        _client.flush_sync()


def shutdown() -> None:
    """Flush and close the SDK client."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
