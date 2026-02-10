"""Drop-in Python logging handler for Argus."""

from __future__ import annotations

import logging
from typing import Any


class ArgusHandler(logging.Handler):
    """Python logging handler that sends log records to Argus."""

    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level)

    def emit(self, record: logging.LogRecord) -> None:
        """Send a log record as a telemetry event."""
        import argus

        if argus._client is None:
            return

        data: dict[str, Any] = {
            "level": record.levelname,
            "message": self.format(record),
            "logger": record.name,
            "filename": record.filename,
            "lineno": record.lineno,
        }

        if record.exc_info and record.exc_info[1]:
            import traceback

            data["exception"] = "".join(traceback.format_exception(*record.exc_info))

        argus._client.send_event("log", data)
