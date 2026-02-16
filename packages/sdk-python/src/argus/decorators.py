"""Decorators for tracing functions."""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, TypeVar

F = TypeVar("F")


def trace(name: str | None = None) -> Any:
    """Decorator that traces function execution time and exceptions.

    Works with both sync and async functions. Creates a span with
    proper parent/child relationships via the trace context.
    """
    def decorator(func: Any) -> Any:
        trace_name = name or func.__qualname__

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                import argus
                from argus.context import get_current_context, set_current_context, start_span

                if argus._client is None:
                    return await func(*args, **kwargs)

                parent_ctx = get_current_context()
                ctx = start_span(trace_name)
                start = time.monotonic()
                try:
                    result = await func(*args, **kwargs)
                    duration = (time.monotonic() - start) * 1000
                    argus._client.send_event("span", {
                        "trace_id": ctx.trace_id,
                        "span_id": ctx.span_id,
                        "parent_span_id": ctx.parent_span_id,
                        "name": trace_name,
                        "kind": "internal",
                        "duration_ms": round(duration, 2),
                        "status": "ok",
                    })
                    return result
                except Exception as exc:
                    duration = (time.monotonic() - start) * 1000
                    argus._client.send_event("span", {
                        "trace_id": ctx.trace_id,
                        "span_id": ctx.span_id,
                        "parent_span_id": ctx.parent_span_id,
                        "name": trace_name,
                        "kind": "internal",
                        "duration_ms": round(duration, 2),
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    })
                    raise
                finally:
                    set_current_context(parent_ctx)

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                import argus
                from argus.context import get_current_context, set_current_context, start_span

                if argus._client is None:
                    return func(*args, **kwargs)

                parent_ctx = get_current_context()
                ctx = start_span(trace_name)
                start = time.monotonic()
                try:
                    result = func(*args, **kwargs)
                    duration = (time.monotonic() - start) * 1000
                    argus._client.send_event("span", {
                        "trace_id": ctx.trace_id,
                        "span_id": ctx.span_id,
                        "parent_span_id": ctx.parent_span_id,
                        "name": trace_name,
                        "kind": "internal",
                        "duration_ms": round(duration, 2),
                        "status": "ok",
                    })
                    return result
                except Exception as exc:
                    duration = (time.monotonic() - start) * 1000
                    argus._client.send_event("span", {
                        "trace_id": ctx.trace_id,
                        "span_id": ctx.span_id,
                        "parent_span_id": ctx.parent_span_id,
                        "name": trace_name,
                        "kind": "internal",
                        "duration_ms": round(duration, 2),
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    })
                    raise
                finally:
                    set_current_context(parent_ctx)

            return sync_wrapper

    return decorator


def _safe_repr(args: tuple[Any, ...]) -> str:
    """Safe repr of function arguments, truncated."""
    try:
        r = repr(args)
        return r[:200] if len(r) > 200 else r
    except Exception:
        return "<args>"
