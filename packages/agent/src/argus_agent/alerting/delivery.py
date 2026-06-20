"""Reliable delivery wrapper for notification channels.

External channels (Slack, email, webhook) each make a single best-effort attempt
and swallow failures, so a brief outage silently drops the alert. This module wraps
any channel send call with bounded retry + backoff and records a durable failure
record once retries are exhausted, so persistent outages are visible instead of
invisible.

Only failures are persisted (after retries), keeping DB writes off the success path.
By design there is no delayed re-delivery loop: re-sending a now-stale alert minutes
or hours later would be noise. Retries cover the common case (a transient blip).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("argus.alerting.delivery")

# Backoff between attempts. Total worst-case added latency ≈ sum(delays).
_RETRY_DELAYS = [1.5, 3.0]
_MAX_ATTEMPTS = 3


def channel_name(channel: Any) -> str:
    """Map a channel instance to a short, stable channel name."""
    name = type(channel).__name__.lower()
    if "slack" in name:
        return "slack"
    if "webhook" in name:
        return "webhook"
    if "email" in name:
        return "email"
    if "websocket" in name:
        return "websocket"
    return name.replace("channel", "") or "unknown"


async def deliver(
    send: Callable[[], Awaitable[Any]],
    *,
    channel: str,
    kind: str,
    alert_id: str = "",
    severity: str = "",
    max_attempts: int = _MAX_ATTEMPTS,
    delays: list[float] | None = None,
) -> Any:
    """Run a channel send with retry + backoff; record a failure if all attempts fail.

    ``send`` is a zero-arg coroutine factory that performs one delivery attempt and
    returns the channel's result. A failure is an exception **or** a return value of
    exactly ``False`` (channels return ``False`` on failure); any other value —
    ``True``, a metadata dict, ``None`` — counts as success and is returned as-is so
    callers keep semantics like Slack thread metadata.

    Returns the last result (the successful result, or the last failing result).
    """
    delays = delays if delays is not None else _RETRY_DELAYS
    last_result: Any = None
    last_error = ""
    attempts = 0

    for attempt in range(max_attempts):
        attempts = attempt + 1
        try:
            last_result = await send()
            if last_result is not False:
                return last_result
            last_error = "channel reported failure"
        except Exception as exc:  # noqa: BLE001 — we retry/record all delivery errors
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Delivery attempt %d/%d failed for %s/%s: %s",
                attempts, max_attempts, channel, kind, last_error,
            )

        if attempt < max_attempts - 1:
            await asyncio.sleep(delays[min(attempt, len(delays) - 1)])

    logger.error(
        "Delivery FAILED after %d attempts for %s/%s alert=%s: %s",
        attempts, channel, kind, alert_id, last_error,
    )
    await _record_failure(
        channel=channel, kind=kind, alert_id=alert_id,
        severity=severity, attempts=attempts, error=last_error,
    )
    return last_result


async def _record_failure(
    *,
    channel: str,
    kind: str,
    alert_id: str,
    severity: str,
    attempts: int,
    error: str,
) -> None:
    """Persist a failed-delivery record. Best-effort: never raises into the caller."""
    try:
        from argus_agent.storage.models import NotificationDelivery
        from argus_agent.storage.repositories import get_session
        from argus_agent.tenancy.context import get_tenant_id

        async with get_session() as session:
            session.add(
                NotificationDelivery(
                    tenant_id=get_tenant_id(),
                    alert_id=alert_id,
                    channel=channel,
                    kind=kind,
                    severity=severity,
                    status="failed",
                    attempts=attempts,
                    error=error[:1000],
                )
            )
            await session.commit()
    except Exception:
        logger.debug("Failed to persist delivery failure record", exc_info=True)


async def list_deliveries(
    *, status: str | None = None, limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent delivery records (most recent first), optionally by status."""
    try:
        from sqlalchemy import select

        from argus_agent.storage.models import NotificationDelivery
        from argus_agent.storage.repositories import get_session

        async with get_session() as session:
            stmt = select(NotificationDelivery).order_by(
                NotificationDelivery.created_at.desc()
            )
            if status:
                stmt = stmt.where(NotificationDelivery.status == status)
            stmt = stmt.limit(max(1, min(limit, 200)))
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": r.id,
                    "alert_id": r.alert_id,
                    "channel": r.channel,
                    "kind": r.kind,
                    "severity": r.severity,
                    "status": r.status,
                    "attempts": r.attempts,
                    "error": r.error,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except Exception:
        logger.debug("Failed to list delivery records", exc_info=True)
        return []
