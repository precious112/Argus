"""SQLite database for operational/transactional data."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from argus_agent.storage.models import Base

logger = logging.getLogger("argus.storage")

_engine: AsyncEngine | None = None
_session_factory: sessionmaker | None = None


async def init_db(db_path: str) -> None:
    """Initialize the SQLite database and create tables."""
    global _engine, _session_factory

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
    )

    # Enable WAL mode for better concurrent access
    @event.listens_for(_engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("SQLite database initialized at %s", db_path)


async def close_db() -> None:
    """Close the database connection."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session() -> AsyncSession:
    """Get a new database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory()
