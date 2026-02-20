"""Database auto-instrumentation for psycopg2."""

from __future__ import annotations

import time
from typing import Any

_original_execute: Any = None


def patch_psycopg2() -> None:
    """Monkey-patch psycopg2 cursor.execute() to capture DB dependency calls."""
    global _original_execute

    try:
        import psycopg2.extensions
    except ImportError:
        return

    if _original_execute is not None:
        return  # Already patched

    _original_execute = psycopg2.extensions.cursor.execute

    def _patched_execute(self: Any, query: Any, vars: Any = None) -> Any:
        import argus
        from argus.context import get_current_context

        start = time.monotonic()
        error_msg = None
        try:
            return _original_execute(self, query, vars)
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            if argus._client:
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                ctx = get_current_context()

                # Determine query type
                query_str = query if isinstance(query, str) else str(query)
                operation = query_str.strip().split()[0].upper() if query_str.strip() else "UNKNOWN"

                # Get database name from connection
                db_name = ""
                try:
                    dsn = self.connection.dsn
                    for part in dsn.split():
                        if part.startswith("dbname="):
                            db_name = part.split("=", 1)[1]
                            break
                except Exception:
                    pass

                argus._client.send_event("dependency", {
                    "trace_id": ctx.trace_id if ctx else None,
                    "span_id": ctx.span_id if ctx else None,
                    "dep_type": "db",
                    "target": db_name or "postgres",
                    "operation": operation,
                    "duration_ms": duration_ms,
                    "status": "error" if error_msg else "ok",
                    "error_message": error_msg,
                })

    psycopg2.extensions.cursor.execute = _patched_execute  # type: ignore[assignment]


def unpatch_psycopg2() -> None:
    """Restore original psycopg2 cursor.execute()."""
    global _original_execute

    if _original_execute is None:
        return

    try:
        import psycopg2.extensions
    except ImportError:
        return

    psycopg2.extensions.cursor.execute = _original_execute  # type: ignore[assignment]
    _original_execute = None
