"""LLM settings service — DB-backed with env/YAML fallback."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from argus_agent.storage.models import AppConfig
from argus_agent.storage.repositories import get_session

logger = logging.getLogger("argus.llm.settings")

_MASK = "••••••••"
_LLM_KEYS = ("llm.provider", "llm.model", "llm.api_key")


class LLMSettingsService:
    """Read/write LLM settings in the AppConfig key-value table."""

    async def get_all(self, masked: bool = True) -> dict[str, Any]:
        """Return DB-persisted LLM settings. Masks API key by default."""
        raw = await self._fetch_llm_keys()
        if masked and raw.get("api_key"):
            raw["api_key"] = _MASK
        return raw

    async def get_raw(self) -> dict[str, Any]:
        """Return DB-persisted LLM settings with full secrets."""
        return await self._fetch_llm_keys()

    async def save(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Upsert LLM settings. Skips masked API key to preserve existing."""
        async with get_session() as session:
            for field in ("provider", "model", "api_key"):
                value = updates.get(field)
                if value is None:
                    continue
                # Don't overwrite with the mask placeholder
                if field == "api_key" and value == _MASK:
                    continue

                db_key = f"llm.{field}"
                stmt = select(AppConfig).where(AppConfig.key == db_key)
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

                if row is None:
                    row = AppConfig(key=db_key, value=str(value))
                    session.add(row)
                else:
                    row.value = str(value)

            await session.commit()

        return await self.get_all(masked=True)

    async def has_persisted_settings(self) -> bool:
        """Check if any LLM keys exist in the DB."""
        async with get_session() as session:
            stmt = select(AppConfig).where(AppConfig.key.in_(_LLM_KEYS))
            result = await session.execute(stmt)
            return result.first() is not None

    async def apply_to_settings(self) -> None:
        """Override the in-memory Settings singleton with DB values.

        Called once at startup after init_db(). If no DB settings exist,
        env/YAML defaults remain untouched.
        """
        raw = await self.get_raw()
        if not raw:
            return

        from argus_agent.config import get_settings

        settings = get_settings()

        if raw.get("provider"):
            settings.llm.provider = raw["provider"]
        if raw.get("model"):
            settings.llm.model = raw["model"]
        if raw.get("api_key"):
            settings.llm.api_key = raw["api_key"]

        logger.info(
            "Applied DB-persisted LLM settings (provider=%s, model=%s)",
            raw.get("provider", "-"),
            raw.get("model", "-"),
        )

    # ---- internal helpers ----

    async def _fetch_llm_keys(self) -> dict[str, Any]:
        """Fetch all llm.* keys from AppConfig."""
        async with get_session() as session:
            stmt = select(AppConfig).where(AppConfig.key.in_(_LLM_KEYS))
            result = await session.execute(stmt)
            rows = result.scalars().all()

        out: dict[str, Any] = {}
        for row in rows:
            # Strip "llm." prefix → "provider", "model", "api_key"
            short = row.key.removeprefix("llm.")
            out[short] = row.value
        return out
