"""Flask middleware for Argus SDK."""

from __future__ import annotations

import time
from typing import Any


class ArgusFlask:
    """Flask extension that logs requests and captures exceptions."""

    def __init__(self, app: Any = None) -> None:
        self._app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Any) -> None:
        """Register hooks with a Flask app."""
        self._app = app
        app.before_request(self._before_request)
        app.after_request(self._after_request)
        app.teardown_request(self._teardown_request)

    def _before_request(self) -> None:
        from flask import g, request

        from argus.context import TraceContext, set_current_context, start_trace

        g._argus_start = time.monotonic()

        # Parse incoming traceparent or start new trace
        traceparent = request.headers.get("traceparent", "")
        if traceparent:
            ctx = TraceContext.from_traceparent(traceparent)
            if ctx:
                set_current_context(ctx)
            else:
                ctx = start_trace()
        else:
            ctx = start_trace()
        g._argus_trace_ctx = ctx

        # Add breadcrumb for request
        try:
            from argus.breadcrumbs import add_breadcrumb
            add_breadcrumb("http", f"{request.method} {request.path}")
        except ImportError:
            pass

    def _after_request(self, response: Any) -> Any:
        from flask import g, request

        import argus
        from argus.context import set_current_context

        ctx = getattr(g, "_argus_trace_ctx", None)
        start = getattr(g, "_argus_start", time.monotonic())
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        if argus._client and ctx:
            span_status = "ok" if response.status_code < 500 else "error"
            argus._client.send_event("span", {
                "trace_id": ctx.trace_id,
                "span_id": ctx.span_id,
                "parent_span_id": ctx.parent_span_id,
                "name": f"{request.method} {request.path}",
                "kind": "server",
                "duration_ms": duration_ms,
                "status": span_status,
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
            })

        # Add traceparent to response
        if ctx:
            response.headers["traceparent"] = ctx.to_traceparent()

        set_current_context(None)
        return response

    def _teardown_request(self, exc: BaseException | None) -> None:
        if exc is not None:
            import argus

            if argus._client:
                argus._client.send_event("exception", {
                    "type": type(exc).__name__,
                    "message": str(exc),
                })
