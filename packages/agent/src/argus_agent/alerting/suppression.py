"""Suppression persistence service — CRUD for acknowledgments and mutes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from argus_agent.storage.database import get_session
from argus_agent.storage.models import AlertAcknowledgment, AlertRuleMute

logger = logging.getLogger("argus.alerting.suppression")


class SuppressionService:
    """Read/write alert acknowledgments and rule mutes in the DB."""

    # --- Acknowledgments ---

    async def acknowledge(
        self,
        dedup_key: str,
        rule_id: str,
        source: str = "",
        acknowledged_by: str = "user",
        reason: str = "",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Create or update an acknowledgment for a dedup_key."""
        async with get_session() as session:
            stmt = select(AlertAcknowledgment).where(
                AlertAcknowledgment.dedup_key == dedup_key,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                row = AlertAcknowledgment(
                    dedup_key=dedup_key,
                    rule_id=rule_id,
                    source=source,
                    acknowledged_by=acknowledged_by,
                    reason=reason,
                    expires_at=expires_at,
                    active=True,
                )
                session.add(row)
            else:
                row.acknowledged_by = acknowledged_by
                row.reason = reason
                row.expires_at = expires_at
                row.active = True

            await session.commit()
            await session.refresh(row)
            return self._ack_to_dict(row)

    async def unacknowledge(self, dedup_key: str) -> bool:
        """Deactivate an acknowledgment."""
        async with get_session() as session:
            stmt = select(AlertAcknowledgment).where(
                AlertAcknowledgment.dedup_key == dedup_key,
                AlertAcknowledgment.active.is_(True),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return False
            row.active = False
            await session.commit()
            return True

    async def get_active_acknowledgments(self) -> list[dict[str, Any]]:
        """Return all active acknowledgments, auto-expiring stale ones."""
        now = datetime.now(UTC)
        async with get_session() as session:
            stmt = select(AlertAcknowledgment).where(
                AlertAcknowledgment.active.is_(True),
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            active = []
            for row in rows:
                if row.expires_at is not None and now >= row.expires_at:
                    row.active = False
                    continue
                active.append(self._ack_to_dict(row))

            await session.commit()
            return active

    # --- Rule Mutes ---

    async def mute_rule(
        self,
        rule_id: str,
        muted_by: str = "user",
        reason: str = "",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Mute a rule. If already muted, update the expiry."""
        async with get_session() as session:
            stmt = select(AlertRuleMute).where(
                AlertRuleMute.rule_id == rule_id,
                AlertRuleMute.active.is_(True),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                row = AlertRuleMute(
                    rule_id=rule_id,
                    muted_by=muted_by,
                    reason=reason,
                    expires_at=expires_at or datetime.now(UTC),
                    active=True,
                )
                session.add(row)
            else:
                row.muted_by = muted_by
                row.reason = reason
                if expires_at:
                    row.expires_at = expires_at

            await session.commit()
            await session.refresh(row)
            return self._mute_to_dict(row)

    async def unmute_rule(self, rule_id: str) -> bool:
        """Deactivate a rule mute."""
        async with get_session() as session:
            stmt = select(AlertRuleMute).where(
                AlertRuleMute.rule_id == rule_id,
                AlertRuleMute.active.is_(True),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return False
            row.active = False
            await session.commit()
            return True

    async def get_active_mutes(self) -> list[dict[str, Any]]:
        """Return all active rule mutes, auto-expiring stale ones."""
        now = datetime.now(UTC)
        async with get_session() as session:
            stmt = select(AlertRuleMute).where(
                AlertRuleMute.active.is_(True),
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            active = []
            for row in rows:
                if now >= row.expires_at:
                    row.active = False
                    continue
                active.append(self._mute_to_dict(row))

            await session.commit()
            return active

    # --- Startup loader ---

    async def load_into_engine(self, engine: Any) -> None:
        """Load persisted acknowledgments and mutes into the in-memory engine."""
        from argus_agent.alerting.engine import AlertEngine

        if not isinstance(engine, AlertEngine):
            return

        acks = await self.get_active_acknowledgments()
        for ack in acks:
            expires = None
            if ack["expires_at"]:
                expires = datetime.fromisoformat(ack["expires_at"])
            engine._acknowledged_keys[ack["dedup_key"]] = expires

        mutes = await self.get_active_mutes()
        for mute in mutes:
            expires = datetime.fromisoformat(mute["expires_at"])
            engine._muted_rules[mute["rule_id"]] = expires

        logger.info(
            "Loaded %d acknowledgments and %d mutes from DB",
            len(acks), len(mutes),
        )

    # --- Helpers ---

    @staticmethod
    def _ack_to_dict(row: AlertAcknowledgment) -> dict[str, Any]:
        return {
            "id": row.id,
            "dedup_key": row.dedup_key,
            "rule_id": row.rule_id,
            "source": row.source,
            "acknowledged_by": row.acknowledged_by,
            "reason": row.reason,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "active": row.active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _mute_to_dict(row: AlertRuleMute) -> dict[str, Any]:
        return {
            "id": row.id,
            "rule_id": row.rule_id,
            "muted_by": row.muted_by,
            "reason": row.reason,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "active": row.active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
