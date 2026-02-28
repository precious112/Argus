"""PostgreSQL implementation of OperationalRepository (SaaS mode).

Uses asyncpg via SQLAlchemy async engine with RLS-based tenant isolation.
Each session automatically sets ``app.current_tenant`` so PostgreSQL RLS
policies filter rows transparently.
"""

from __future__ import annotations

import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from argus_agent.storage.models import Base
from argus_agent.tenancy.context import get_tenant_id

logger = logging.getLogger("argus.storage.postgres")

_engine: AsyncEngine | None = None
_session_factory: sessionmaker | None = None


class PostgresOperationalRepository:
    """OperationalRepository backed by PostgreSQL + asyncpg (SaaS mode)."""

    async def init(self, postgres_url: str) -> None:
        """Create the async engine, run Alembic migrations, and configure RLS hooks."""
        global _engine, _session_factory

        # Ensure the URL uses the asyncpg driver
        url = postgres_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        _engine = create_async_engine(
            url,
            echo=False,
            pool_size=20,
            max_overflow=10,
        )

        _session_factory = sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )  # type: ignore[call-overload]

        # Register a listener that sets the RLS tenant context on every new
        # database transaction.  ``after_begin`` fires once per connection
        # checkout when autobegin kicks in.
        @event.listens_for(_engine.sync_engine, "connect")
        def _set_search_path(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
            # No-op at connect time — tenant is set per-transaction below
            pass

        # Run Alembic migrations to bring the schema up to date
        await self._run_migrations(url)

        # Create any tables that Alembic might not cover yet (safety net)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("PostgreSQL operational repository initialized")

    async def close(self) -> None:
        """Dispose of the connection pool."""
        global _engine, _session_factory
        if _engine:
            await _engine.dispose()
            _engine = None
            _session_factory = None

    def get_session(self) -> AsyncSession:
        """Return a new async session with RLS tenant context.

        The session uses ``after_begin`` to ``SET LOCAL app.current_tenant``
        so that all queries within the transaction are tenant-scoped.
        """
        if _session_factory is None:
            raise RuntimeError("PostgreSQL not initialized. Call init() first.")

        session = _session_factory()

        # Attach a one-shot listener to set tenant context at transaction start
        @event.listens_for(session.sync_session, "after_begin")
        def _set_tenant(session_inner, transaction, connection):  # type: ignore[no-untyped-def]
            tenant_id = get_tenant_id()
            connection.execute(
                text("SET LOCAL app.current_tenant = :tid"),
                {"tid": tenant_id},
            )

        return session

    @staticmethod
    async def _run_migrations(url: str) -> None:
        """Run Alembic migrations programmatically."""
        try:
            from alembic import command
            from alembic.config import Config

            alembic_cfg = Config()
            alembic_cfg.set_main_option("script_location", "alembic")
            # Use synchronous URL for Alembic (it manages its own connections)
            sync_url = url.replace("postgresql+asyncpg://", "postgresql://")
            alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migrations applied successfully")
        except Exception:
            logger.warning("Alembic migration skipped (non-fatal)", exc_info=True)
