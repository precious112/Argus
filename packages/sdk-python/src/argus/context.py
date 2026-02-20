"""Async-safe trace context propagation using contextvars."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from uuid import uuid4

_trace_context_var: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "argus_trace_context", default=None
)


@dataclass
class TraceContext:
    """W3C-compatible trace context."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    baggage: dict[str, str] = field(default_factory=dict)

    def to_traceparent(self) -> str:
        """Serialize to W3C traceparent header value."""
        return f"00-{self.trace_id}-{self.span_id}-01"

    @staticmethod
    def from_traceparent(header: str) -> TraceContext | None:
        """Parse a W3C traceparent header value."""
        parts = header.strip().split("-")
        if len(parts) < 4:
            return None
        return TraceContext(trace_id=parts[1], span_id=parts[2])


def _generate_trace_id() -> str:
    return uuid4().hex


def _generate_span_id() -> str:
    return uuid4().hex[:16]


def start_trace(baggage: dict[str, str] | None = None) -> TraceContext:
    """Start a new root trace and set it as the current context."""
    ctx = TraceContext(
        trace_id=_generate_trace_id(),
        span_id=_generate_span_id(),
        baggage=baggage or {},
    )
    _trace_context_var.set(ctx)
    return ctx


def start_span(name: str = "") -> TraceContext:
    """Start a child span under the current trace context.

    If no trace context exists, starts a new root trace.
    """
    parent = _trace_context_var.get()
    if parent is None:
        return start_trace()

    ctx = TraceContext(
        trace_id=parent.trace_id,
        span_id=_generate_span_id(),
        parent_span_id=parent.span_id,
        baggage=dict(parent.baggage),
    )
    _trace_context_var.set(ctx)
    return ctx


def get_current_context() -> TraceContext | None:
    """Get the current trace context, or None if not in a trace."""
    return _trace_context_var.get()


def set_current_context(ctx: TraceContext | None) -> None:
    """Explicitly set (or clear) the current trace context."""
    _trace_context_var.set(ctx)
