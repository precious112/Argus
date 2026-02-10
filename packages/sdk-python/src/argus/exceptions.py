"""Automatic exception capture."""

from __future__ import annotations

import sys
import traceback
from types import TracebackType


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
    argus._client.send_event("exception", {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": tb,
    })
