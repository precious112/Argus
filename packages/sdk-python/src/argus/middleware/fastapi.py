"""FastAPI middleware for Argus SDK."""

from __future__ import annotations

import time
from typing import Any


class ArgusMiddleware:
    """ASGI middleware that logs requests/responses and captures exceptions."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import argus
        from argus.context import (
            TraceContext,
            get_current_context,
            set_current_context,
            start_trace,
        )

        method = scope.get("method", "")
        path = scope.get("path", "")
        status_code = 500

        # Parse incoming traceparent header or start new trace
        headers = dict(scope.get("headers", []))
        traceparent = headers.get(b"traceparent", b"").decode("utf-8", errors="ignore")

        if traceparent:
            ctx = TraceContext.from_traceparent(traceparent)
            if ctx:
                set_current_context(ctx)
            else:
                ctx = start_trace()
        else:
            ctx = start_trace()

        # Add breadcrumb for request
        try:
            from argus.breadcrumbs import add_breadcrumb
            add_breadcrumb("http", f"{method} {path}")
        except ImportError:
            pass

        start = time.monotonic()

        async def send_wrapper(message: Any) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                # Inject traceparent response header
                resp_headers = list(message.get("headers", []))
                current = get_current_context()
                if current:
                    resp_headers.append(
                        (b"traceparent", current.to_traceparent().encode())
                    )
                message = {**message, "headers": resp_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if argus._client:
                argus._client.send_event("exception", {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "path": path,
                    "method": method,
                })
            raise
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            if argus._client:
                span_status = "ok" if status_code < 500 else "error"
                argus._client.send_event("span", {
                    "trace_id": ctx.trace_id,
                    "span_id": ctx.span_id,
                    "parent_span_id": ctx.parent_span_id,
                    "name": f"{method} {path}",
                    "kind": "server",
                    "duration_ms": duration_ms,
                    "status": span_status,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                })
            set_current_context(None)
