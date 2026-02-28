"""Notification channel settings service — CRUD over SQLite."""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any

from sqlalchemy import select

from argus_agent.config import AlertConfig
from argus_agent.storage.models import NotificationChannelConfig
from argus_agent.storage.repositories import get_session

logger = logging.getLogger("argus.alerting.settings")

# Keys that contain secrets and should be masked in API responses
_SECRET_KEYS = frozenset({"bot_token", "smtp_password"})
_MASK = "••••••••"


class NotificationSettingsService:
    """Read/write notification channel configs in the DB."""

    async def get_all(self) -> list[dict[str, Any]]:
        """Return all channel configs with secrets masked."""
        rows = await self._fetch_all()
        return [self._mask(r) for r in rows]

    async def get_all_raw(self) -> list[dict[str, Any]]:
        """Return all channel configs with full secrets (for building channels)."""
        return await self._fetch_all()

    async def get_by_type(self, channel_type: str) -> dict[str, Any] | None:
        """Return a single channel config by type, secrets masked."""
        async with get_session() as session:
            stmt = select(NotificationChannelConfig).where(
                NotificationChannelConfig.channel_type == channel_type,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._mask(self._row_to_dict(row))

    async def get_by_type_raw(self, channel_type: str) -> dict[str, Any] | None:
        """Return a single channel config by type, with full secrets."""
        async with get_session() as session:
            stmt = select(NotificationChannelConfig).where(
                NotificationChannelConfig.channel_type == channel_type,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._row_to_dict(row)

    async def upsert(
        self,
        channel_type: str,
        enabled: bool,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or update a channel config. Returns the masked result."""
        async with get_session() as session:
            stmt = select(NotificationChannelConfig).where(
                NotificationChannelConfig.channel_type == channel_type,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                row = NotificationChannelConfig(
                    id=str(uuid.uuid4()),
                    channel_type=channel_type,
                    enabled=enabled,
                    config=config,
                )
                session.add(row)
            else:
                # Merge: keep existing secret values when the caller sends the mask
                merged = self._merge_config(row.config or {}, config)
                row.enabled = enabled
                row.config = merged

            await session.commit()
            await session.refresh(row)
            return self._mask(self._row_to_dict(row))

    async def delete(self, channel_type: str) -> bool:
        """Delete a channel config. Returns True if something was deleted."""
        async with get_session() as session:
            stmt = select(NotificationChannelConfig).where(
                NotificationChannelConfig.channel_type == channel_type,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def initialize_from_config(self, alert_config: AlertConfig) -> None:
        """Seed DB from YAML/env config on first run (skip if rows exist)."""
        # Webhook
        if alert_config.webhook_urls:
            existing = await self.get_by_type_raw("webhook")
            if existing is None:
                await self.upsert("webhook", True, {"urls": alert_config.webhook_urls})
                logger.info("Seeded webhook config from static config")

        # Email
        if alert_config.email_enabled:
            existing = await self.get_by_type_raw("email")
            if existing is None:
                await self.upsert("email", True, {
                    "smtp_host": alert_config.email_smtp_host,
                    "smtp_port": alert_config.email_smtp_port,
                    "from_addr": alert_config.email_from,
                    "to_addrs": alert_config.email_to,
                    "smtp_user": "",
                    "smtp_password": "",
                    "use_tls": True,
                })
                logger.info("Seeded email config from static config")

    # ---- internal helpers ----

    async def _fetch_all(self) -> list[dict[str, Any]]:
        async with get_session() as session:
            stmt = select(NotificationChannelConfig).order_by(
                NotificationChannelConfig.channel_type,
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars().all()]

    @staticmethod
    def _row_to_dict(row: NotificationChannelConfig) -> dict[str, Any]:
        return {
            "id": row.id,
            "channel_type": row.channel_type,
            "enabled": row.enabled,
            "config": row.config or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def _mask(data: dict[str, Any]) -> dict[str, Any]:
        """Return a copy with secret fields replaced by a mask."""
        out = copy.deepcopy(data)
        cfg = out.get("config", {})
        for key in _SECRET_KEYS:
            if key in cfg and cfg[key]:
                cfg[key] = _MASK
        return out

    @staticmethod
    def _merge_config(
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge incoming config, preserving existing secret values when masked."""
        merged = {**existing, **incoming}
        for key in _SECRET_KEYS:
            if incoming.get(key) == _MASK and key in existing:
                merged[key] = existing[key]
        return merged
