"""SQLite implementation of OperationalRepository.

Thin wrapper that delegates to the existing functions in ``database.py``.
This preserves backward compatibility while allowing the SaaS mode to
swap to a PostgreSQL implementation later.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from argus_agent.storage import database


class SQLiteOperationalRepository:
    """OperationalRepository backed by SQLite (self-hosted mode)."""

    async def init(self, db_path: str) -> None:
        await database.init_db(db_path)

    async def close(self) -> None:
        await database.close_db()

    def get_session(self) -> AsyncSession:
        return database.get_session()
