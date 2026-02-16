"""Breadcrumb trail for error context."""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

_MAX_BREADCRUMBS = 50

_local = threading.local()


def _get_crumbs() -> deque[dict[str, Any]]:
    if not hasattr(_local, "breadcrumbs"):
        _local.breadcrumbs = deque(maxlen=_MAX_BREADCRUMBS)
    return _local.breadcrumbs


def add_breadcrumb(
    category: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Add a breadcrumb to the current thread's trail."""
    crumbs = _get_crumbs()
    crumbs.append({
        "timestamp": datetime.now(UTC).isoformat(),
        "category": category,
        "message": message,
        "data": data or {},
    })


def get_breadcrumbs() -> list[dict[str, Any]]:
    """Return all breadcrumbs for the current thread."""
    return list(_get_crumbs())


def clear_breadcrumbs() -> None:
    """Clear the current thread's breadcrumb trail."""
    _get_crumbs().clear()
