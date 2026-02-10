"""Decorators for tracing functions."""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, TypeVar

F = TypeVar("F")


def trace(name: str | None = None) -> Any:
    """Decorator that traces function execution time and exceptions.

    Works with both sync and async functions.
    """
    def decorator(func: Any) -> Any:
        trace_name = name or func.__qualname__

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                import argus

                if argus._client is None:
                    return await func(*args, **kwargs)

                argus._client.send_event("trace_start", {
                    "name": trace_name,
                    "args": _safe_repr(args),
                })
                start = time.monotonic()
                try:
                    result = await func(*args, **kwargs)
                    duration = (time.monotonic() - start) * 1000
                    argus._client.send_event("trace_end", {
                        "name": trace_name,
                        "duration_ms": round(duration, 2),
                    })
                    return result
                except Exception as exc:
                    duration = (time.monotonic() - start) * 1000
                    argus._client.send_event("trace_end", {
                        "name": trace_name,
                        "duration_ms": round(duration, 2),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    })
                    raise

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                import argus

                if argus._client is None:
                    return func(*args, **kwargs)

                argus._client.send_event("trace_start", {
                    "name": trace_name,
                    "args": _safe_repr(args),
                })
                start = time.monotonic()
                try:
                    result = func(*args, **kwargs)
                    duration = (time.monotonic() - start) * 1000
                    argus._client.send_event("trace_end", {
                        "name": trace_name,
                        "duration_ms": round(duration, 2),
                    })
                    return result
                except Exception as exc:
                    duration = (time.monotonic() - start) * 1000
                    argus._client.send_event("trace_end", {
                        "name": trace_name,
                        "duration_ms": round(duration, 2),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    })
                    raise

            return sync_wrapper

    return decorator


def _safe_repr(args: tuple[Any, ...]) -> str:
    """Safe repr of function arguments, truncated."""
    try:
        r = repr(args)
        return r[:200] if len(r) > 200 else r
    except Exception:
        return "<args>"
