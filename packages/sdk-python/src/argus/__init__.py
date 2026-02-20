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
    runtime_metrics: bool = False,
    auto_instrument: bool = False,
) -> None:
    """Initialize the Argus SDK. Must be called before other methods."""
    global _client
    from argus.client import _SERVERLESS_BATCH_SIZE, _SERVERLESS_FLUSH_INTERVAL, ArgusClient
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

    # Start runtime metrics collector
    if runtime_metrics:
        from argus.runtime import RuntimeMetricsCollector

        collector = RuntimeMetricsCollector(_client)
        collector.start()

    # Enable auto-instrumentation
    if auto_instrument:
        try:
            from argus.integrations.http import patch_httpx
            patch_httpx()
        except Exception:
            pass
        try:
            from argus.integrations.database import patch_psycopg2
            patch_psycopg2()
        except Exception:
            pass

    # Send deploy event with version info
    deploy_data = _detect_version_info()
    if deploy_data:
        _client.send_event("deploy", {
            "service": service_name,
            **deploy_data,
        })


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
    event_data: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": tb,
    }

    # Attach trace context
    try:
        from argus.context import get_current_context

        ctx = get_current_context()
        if ctx:
            event_data["trace_id"] = ctx.trace_id
            event_data["span_id"] = ctx.span_id
    except ImportError:
        pass

    # Attach breadcrumbs
    try:
        from argus.breadcrumbs import clear_breadcrumbs, get_breadcrumbs

        crumbs = get_breadcrumbs()
        if crumbs:
            event_data["breadcrumbs"] = crumbs
            clear_breadcrumbs()
    except ImportError:
        pass

    _client.send_event("exception", event_data)


def add_breadcrumb(
    category: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Add a breadcrumb to the current trail."""
    from argus.breadcrumbs import add_breadcrumb as _add
    _add(category, message, data)


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


def _detect_version_info() -> dict[str, str]:
    """Detect the current application version/git SHA."""
    import os

    data: dict[str, str] = {"sdk_version": __version__}

    # Try environment variables for git SHA
    sha_env_vars = [
        "GIT_SHA", "COMMIT_SHA",
        "VERCEL_GIT_COMMIT_SHA", "RAILWAY_GIT_COMMIT_SHA",
        "RENDER_GIT_COMMIT", "HEROKU_SLUG_COMMIT",
    ]
    for env_var in sha_env_vars:
        val = os.environ.get(env_var)
        if val:
            data["git_sha"] = val
            break

    # Fallback to git rev-parse
    if "git_sha" not in data:
        try:
            import subprocess

            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                data["git_sha"] = result.stdout.strip()
        except Exception:
            pass

    # Environment
    data["environment"] = (
        os.environ.get("ENVIRONMENT")
        or os.environ.get("ENV")
        or os.environ.get("NODE_ENV")
        or ""
    )

    return data
