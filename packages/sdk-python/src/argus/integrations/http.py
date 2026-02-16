"""HTTP auto-instrumentation for httpx."""

from __future__ import annotations

import time
from typing import Any

_original_sync_send: Any = None
_original_async_send: Any = None


def patch_httpx() -> None:
    """Monkey-patch httpx to capture outgoing HTTP dependency calls."""
    global _original_sync_send, _original_async_send

    try:
        import httpx
    except ImportError:
        return

    if _original_sync_send is not None:
        return  # Already patched

    _original_sync_send = httpx.Client.send
    _original_async_send = httpx.AsyncClient.send

    def _patched_sync_send(self: Any, request: Any, **kwargs: Any) -> Any:
        import argus
        from argus.context import get_current_context

        start = time.monotonic()
        status_code = 0
        error_msg = None
        try:
            response = _original_sync_send(self, request, **kwargs)
            status_code = response.status_code
            return response
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            if argus._client:
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                ctx = get_current_context()
                dep_status = "ok" if (200 <= status_code < 400) else "error"
                if error_msg:
                    dep_status = "error"

                # Inject traceparent if context available
                target = f"{request.url.host}:{request.url.port or 443}"
                argus._client.send_event("dependency", {
                    "trace_id": ctx.trace_id if ctx else None,
                    "span_id": ctx.span_id if ctx else None,
                    "dep_type": "http",
                    "target": target,
                    "operation": str(request.method),
                    "url": str(request.url),
                    "duration_ms": duration_ms,
                    "status": dep_status,
                    "status_code": status_code,
                    "error_message": error_msg,
                })

    async def _patched_async_send(self: Any, request: Any, **kwargs: Any) -> Any:
        import argus
        from argus.context import get_current_context

        start = time.monotonic()
        status_code = 0
        error_msg = None
        try:
            response = await _original_async_send(self, request, **kwargs)
            status_code = response.status_code
            return response
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            if argus._client:
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                ctx = get_current_context()
                dep_status = "ok" if (200 <= status_code < 400) else "error"
                if error_msg:
                    dep_status = "error"

                target = f"{request.url.host}:{request.url.port or 443}"
                argus._client.send_event("dependency", {
                    "trace_id": ctx.trace_id if ctx else None,
                    "span_id": ctx.span_id if ctx else None,
                    "dep_type": "http",
                    "target": target,
                    "operation": str(request.method),
                    "url": str(request.url),
                    "duration_ms": duration_ms,
                    "status": dep_status,
                    "status_code": status_code,
                    "error_message": error_msg,
                })

    httpx.Client.send = _patched_sync_send  # type: ignore[assignment]
    httpx.AsyncClient.send = _patched_async_send  # type: ignore[assignment]


def unpatch_httpx() -> None:
    """Restore original httpx methods."""
    global _original_sync_send, _original_async_send

    if _original_sync_send is None:
        return

    try:
        import httpx
    except ImportError:
        return

    httpx.Client.send = _original_sync_send  # type: ignore[assignment]
    httpx.AsyncClient.send = _original_async_send  # type: ignore[assignment]
    _original_sync_send = None
    _original_async_send = None
