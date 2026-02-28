"""Alert history persistence service."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, update

from argus_agent.storage.models import AlertHistory
from argus_agent.storage.repositories import get_session

logger = logging.getLogger("argus.storage.alert_history")

_UNSET = object()  # sentinel to distinguish "not provided" from None


class AlertHistoryService:
    """Persist and query alert history from the database."""

    async def save(self, alert: Any, event: Any) -> int:
        """Insert a new AlertHistory row from an ActiveAlert + Event.

        Returns the row ID.
        """
        async with get_session() as session:
            entry = AlertHistory(
                alert_id=alert.id,
                rule_id=alert.rule_id,
                rule_name=alert.rule_name,
                timestamp=alert.timestamp,
                severity=str(alert.severity),
                title=alert.rule_name,
                message=event.message,
                event_type=str(event.type),
                source=str(event.source),
                status=str(alert.status),
            )
            session.add(entry)
            await session.flush()
            entry_id = entry.id
            await session.commit()
            return entry_id

    async def update_status(
        self,
        alert_id: str,
        *,
        status: Any = _UNSET,
        resolved: Any = _UNSET,
        resolved_at: Any = _UNSET,
        acknowledged_at: Any = _UNSET,
        acknowledged_by: Any = _UNSET,
    ) -> bool:
        """Update status fields for an alert by its alert_id.

        Use ``None`` to explicitly clear nullable fields (e.g. acknowledged_at).
        Omit a parameter (or pass ``_UNSET``) to leave it unchanged.
        """
        values: dict[str, Any] = {}
        if status is not _UNSET:
            values["status"] = status
        if resolved is not _UNSET:
            values["resolved"] = resolved
        if resolved_at is not _UNSET:
            values["resolved_at"] = resolved_at
        if acknowledged_at is not _UNSET:
            values["acknowledged_at"] = acknowledged_at
        if acknowledged_by is not _UNSET:
            values["acknowledged_by"] = acknowledged_by

        if not values:
            return False

        async with get_session() as session:
            stmt = (
                update(AlertHistory)
                .where(AlertHistory.alert_id == alert_id)
                .values(**values)
            )
            result = await session.execute(stmt)
            await session.commit()
            return (result.rowcount or 0) > 0

    async def get_by_alert_id(self, alert_id: str) -> dict[str, Any] | None:
        """Look up a single alert by its alert_id. Returns None if not found."""
        async with get_session() as session:
            stmt = select(AlertHistory).where(AlertHistory.alert_id == alert_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.alert_id,
                "rule_id": row.rule_id,
                "rule_name": row.rule_name,
                "severity": row.severity,
                "message": row.message,
                "source": row.source,
                "event_type": row.event_type,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "resolved": row.resolved,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                "status": row.status,
                "acknowledged_at": (
                    row.acknowledged_at.isoformat() if row.acknowledged_at else None
                ),
                "acknowledged_by": row.acknowledged_by or None,
            }

    async def list_alerts(
        self,
        *,
        resolved: bool | None = None,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query AlertHistory with optional filters and pagination.

        Returns a tuple of (items, total_count).
        """
        async with get_session() as session:
            # Build base filter conditions
            conditions = []
            if resolved is not None:
                conditions.append(AlertHistory.resolved == resolved)
            if severity:
                conditions.append(AlertHistory.severity == severity.upper())
            if status:
                conditions.append(AlertHistory.status == status.lower())

            # Count query
            count_stmt = select(func.count(AlertHistory.id))
            for cond in conditions:
                count_stmt = count_stmt.where(cond)
            total = (await session.execute(count_stmt)).scalar() or 0

            # Data query with pagination
            stmt = select(AlertHistory).order_by(AlertHistory.timestamp.desc())
            for cond in conditions:
                stmt = stmt.where(cond)
            stmt = stmt.limit(limit).offset(offset)

            result = await session.execute(stmt)
            rows = result.scalars().all()

            items = [
                {
                    "id": row.alert_id,
                    "rule_id": row.rule_id,
                    "rule_name": row.rule_name,
                    "severity": row.severity,
                    "message": row.message,
                    "source": row.source,
                    "event_type": row.event_type,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                    "resolved": row.resolved,
                    "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                    "status": row.status,
                    "acknowledged_at": (
                        row.acknowledged_at.isoformat() if row.acknowledged_at else None
                    ),
                    "acknowledged_by": row.acknowledged_by or None,
                }
                for row in rows
            ]
            return items, total
