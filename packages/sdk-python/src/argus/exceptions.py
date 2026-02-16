"""Automatic exception capture."""

from __future__ import annotations

import sys
import traceback
from types import TracebackType
from typing import Any

_original_excepthook = sys.excepthook


def install() -> None:
    """Install a global exception hook that captures unhandled exceptions."""
    sys.excepthook = _argus_excepthook


def _argus_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Exception hook that sends to Argus, then calls the original."""
    capture(exc_value)
    _original_excepthook(exc_type, exc_value, exc_tb)


def capture(exc: BaseException) -> None:
    """Manually capture an exception and send to Argus."""
    import argus

    if argus._client is None:
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

    argus._client.send_event("exception", event_data)
