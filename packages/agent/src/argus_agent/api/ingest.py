"""SDK telemetry ingestion endpoint."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("argus.ingest")

router = APIRouter(tags=["ingest"])

MAX_EVENTS_PER_BATCH = 1000


class TelemetryEvent(BaseModel):
    """A single telemetry event from an SDK."""

    type: str  # log, metric, trace_start, trace_end, exception, event
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
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
    if len(batch.events) > MAX_EVENTS_PER_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Batch too large: {len(batch.events)} events (max {MAX_EVENTS_PER_BATCH})",
        )

    service = batch.service
    stored = 0

    try:
        from argus_agent.storage.timeseries import get_connection

        conn = get_connection()
        for ev in batch.events:
            ev_service = ev.service or service
            conn.execute(
                "INSERT INTO sdk_events VALUES (?, ?, ?, ?)",
                [ev.timestamp, ev_service, ev.type, json.dumps(ev.data)],
            )
            stored += 1
    except RuntimeError:
        # DuckDB not initialized (testing or startup race)
        logger.warning("DuckDB not initialized, events dropped")
    except Exception:
        logger.exception("Failed to store SDK events")

    # Classify error events through the event bus
    try:
        from argus_agent.events.bus import get_event_bus
        from argus_agent.events.types import Event, EventSeverity, EventSource, EventType

        bus = get_event_bus()
        for ev in batch.events:
            if ev.type == "exception":
                bus.publish(Event(
                    source=EventSource.SDK_TELEMETRY,
                    type=EventType.ERROR_BURST,
                    severity=EventSeverity.NOTABLE,
                    data={"service": ev.service or service, **ev.data},
                    message=(
                        f"Exception from {ev.service or service}: "
                        f"{ev.data.get('message', 'unknown')}"
                    ),
                ))
    except Exception:
        logger.debug("Event bus not available for SDK event classification")

    logger.debug("Ingested %d events from %s (%s)", stored, batch.sdk, service)
    return {
        "accepted": stored,
        "timestamp": datetime.now(UTC).isoformat(),
    }
