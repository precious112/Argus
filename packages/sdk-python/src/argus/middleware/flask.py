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
        from flask import g

        g._argus_start = time.monotonic()

    def _after_request(self, response: Any) -> Any:
        import argus
        from flask import g, request

        duration_ms = round((time.monotonic() - getattr(g, "_argus_start", time.monotonic())) * 1000, 2)
        if argus._client:
            argus._client.send_event("log", {
                "level": "ERROR" if response.status_code >= 500 else "INFO",
                "message": f"{request.method} {request.path} {response.status_code} ({duration_ms}ms)",
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            })
        return response

    def _teardown_request(self, exc: BaseException | None) -> None:
        if exc is not None:
            import argus

            if argus._client:
                argus._client.send_event("exception", {
                    "type": type(exc).__name__,
                    "message": str(exc),
                })
