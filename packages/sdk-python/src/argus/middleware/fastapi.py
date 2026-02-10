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

        start = time.monotonic()
        method = scope.get("method", "")
        path = scope.get("path", "")
        status_code = 500

        async def send_wrapper(message: Any) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
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
                argus._client.send_event("log", {
                    "level": "ERROR" if status_code >= 500 else "INFO",
                    "message": f"{method} {path} {status_code} ({duration_ms}ms)",
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                })
