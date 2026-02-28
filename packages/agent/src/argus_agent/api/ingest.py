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
        from argus_agent.storage.repositories import get_metrics_repository

        repo = get_metrics_repository()
        for ev in batch.events:
            ev_service = ev.service or service

            # Store in sdk_events for backward compatibility
            repo.insert_sdk_event(ev.timestamp, ev_service, ev.type, json.dumps(ev.data))

            # Route to specialised Phase 1 tables
            _route_event(repo, ev, ev_service)

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
                await bus.publish(Event(
                    source=EventSource.SDK_TELEMETRY,
                    type=EventType.ERROR_BURST,
                    severity=EventSeverity.URGENT,
                    data={"service": ev.service or service, **ev.data},
                    message=(
                        f"Exception from {ev.service or service}: "
                        f"{ev.data.get('message', 'unknown')}"
                    ),
                ))
    except Exception:
        logger.debug("Event bus not available for SDK event classification")

    # Detect deploy version changes
    try:
        _check_deploys(batch.events, service)
    except Exception:
        logger.debug("Deploy check failed")

    logger.debug("Ingested %d events from %s (%s)", stored, batch.sdk, service)
    return {
        "accepted": stored,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _route_event(
    repo: Any,
    ev: TelemetryEvent,
    service: str,
) -> None:
    """Route an event to the appropriate Phase 1 specialised table."""
    d = ev.data

    if ev.type == "span":
        repo.insert_span(
            trace_id=d.get("trace_id", ""),
            span_id=d.get("span_id", ""),
            service=service,
            name=d.get("name", ""),
            kind=d.get("kind", "internal"),
            parent_span_id=d.get("parent_span_id"),
            duration_ms=d.get("duration_ms"),
            status=d.get("status", "ok"),
            error_type=d.get("error_type"),
            error_message=d.get("error_message"),
            data=d,
            timestamp=ev.timestamp,
        )

    elif ev.type == "dependency":
        repo.insert_dependency_call(
            service=service,
            dep_type=d.get("dep_type", "unknown"),
            target=d.get("target", ""),
            trace_id=d.get("trace_id"),
            span_id=d.get("span_id"),
            parent_span_id=d.get("parent_span_id"),
            operation=d.get("operation", ""),
            duration_ms=d.get("duration_ms"),
            status=d.get("status", "ok"),
            status_code=d.get("status_code"),
            error_message=d.get("error_message"),
            data=d,
            timestamp=ev.timestamp,
        )

    elif ev.type == "runtime_metric":
        repo.insert_sdk_metric(
            service=service,
            metric_name=d.get("metric_name", ""),
            value=d.get("value", 0),
            labels=d.get("labels", {}),
            timestamp=ev.timestamp,
        )

    elif ev.type == "deploy":
        prev = repo.get_previous_deploy_version(service)
        repo.insert_deploy_event(
            service=service,
            version=d.get("version", ""),
            git_sha=d.get("git_sha", ""),
            environment=d.get("environment", ""),
            previous_version=prev or "",
            data=d,
            timestamp=ev.timestamp,
        )


def _check_deploys(events: list[TelemetryEvent], default_service: str) -> None:
    """Publish DEPLOY_DETECTED if a deploy event has a new version."""
    from argus_agent.events.bus import get_event_bus
    from argus_agent.events.types import Event, EventSeverity, EventSource, EventType

    bus = get_event_bus()
    for ev in events:
        if ev.type != "deploy":
            continue
        svc = ev.service or default_service
        git_sha = ev.data.get("git_sha", "")
        if not git_sha:
            continue

        # The routing already stored prev_version in the deploy row
        prev_version = ev.data.get("_previous_version", "")
        if prev_version and prev_version != git_sha:
            bus.publish_nowait(Event(
                source=EventSource.SDK_TELEMETRY,
                type=EventType.DEPLOY_DETECTED,
                severity=EventSeverity.NOTABLE,
                data={"service": svc, "git_sha": git_sha, "previous": prev_version},
                message=f"New deploy detected for '{svc}': {git_sha[:12]}",
            ))
