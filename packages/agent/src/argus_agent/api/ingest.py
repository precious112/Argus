"""SDK telemetry ingestion endpoint."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

logger = logging.getLogger("argus.ingest")

router = APIRouter(tags=["ingest"])


class TelemetryEvent(BaseModel):
    """A single telemetry event from an SDK."""

    type: str  # log, metric, trace, exception, event
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    service: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class IngestBatch(BaseModel):
    """Batch of telemetry events from an SDK."""

    events: list[TelemetryEvent]
    sdk: str = ""  # e.g., "argus-python/0.1.0"
    service: str = ""


@router.post("/ingest")
async def ingest_telemetry(
    batch: IngestBatch,
    x_argus_key: str | None = Header(None),
) -> dict[str, Any]:
    """Receive batched telemetry events from SDKs."""
    # TODO: Validate API key when auth is implemented
    # TODO: Store events in DuckDB
    logger.debug("Ingested %d events from %s", len(batch.events), batch.sdk)
    return {
        "accepted": len(batch.events),
        "timestamp": datetime.now(UTC).isoformat(),
    }
