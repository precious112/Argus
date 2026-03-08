"""PostgreSQL implementation of OperationalRepository (SaaS mode).

Uses asyncpg via SQLAlchemy async engine with RLS-based tenant isolation.
Each session automatically sets ``app.current_tenant`` so PostgreSQL RLS
policies filter rows transparently.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from argus_agent.storage.models import Base
from argus_agent.tenancy.context import get_tenant_id

logger = logging.getLogger("argus.storage.postgres")

_engine: AsyncEngine | None = None
_session_factory: sessionmaker | None = None


def get_raw_session() -> AsyncSession | None:
    """Return a raw AsyncSession WITHOUT RLS for cross-tenant admin queries."""
    if not _engine:
        return None
    return AsyncSession(_engine, expire_on_commit=False)


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
        try:
            async with _engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        except Exception:
            logger.debug("create_all skipped (tables likely already exist)", exc_info=True)

        # Enable RLS on all tables (idempotent safety net)
        await self._ensure_rls()

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

        # Attach a one-shot listener to set tenant context at transaction start.
        # SET LOCAL does not support parameterized values in PostgreSQL,
        # so we use a quoted literal.  The tenant_id comes from our own
        # context (not user input), but we sanitize it to be safe.
        @event.listens_for(session.sync_session, "after_begin")
        def _set_tenant(session_inner, transaction, connection):  # type: ignore[no-untyped-def]
            tenant_id = get_tenant_id()
            safe_tid = tenant_id.replace("'", "''")
            connection.execute(
                text(f"SET LOCAL app.current_tenant = '{safe_tid}'"),
            )
            # Switch to non-superuser role so RLS policies are enforced.
            # Superusers bypass RLS — SET LOCAL ROLE drops privileges for
            # this transaction only, reverting automatically on commit.
            connection.execute(text("SET LOCAL ROLE argus_app"))

        return session

    @staticmethod
    async def _run_migrations(url: str) -> None:
        """Run Alembic migrations with advisory lock to prevent races."""
        try:
            import asyncpg
            from alembic import command
            from alembic.config import Config

            # Connect via asyncpg to grab an advisory lock
            dsn = url.replace("postgresql+asyncpg://", "postgresql://")
            lock_conn = await asyncpg.connect(dsn)
            try:
                acquired = await lock_conn.fetchval(
                    "SELECT pg_try_advisory_lock(1)"
                )
                if not acquired:
                    logger.info("Another process is running migrations, skipping")
                    return

                alembic_cfg = Config()
                _pkg_root = Path(__file__).resolve().parents[3]
                alembic_cfg.set_main_option(
                    "script_location", str(_pkg_root / "alembic"),
                )
                alembic_cfg.set_main_option("sqlalchemy.url", url)
                command.upgrade(alembic_cfg, "head")
                logger.info("Alembic migrations applied successfully")
            finally:
                await lock_conn.execute("SELECT pg_advisory_unlock(1)")
                await lock_conn.close()
        except Exception:
            logger.warning("Alembic migration skipped (non-fatal)", exc_info=True)

    async def _ensure_rls(self) -> None:
        """Enable RLS + create tenant isolation policies on all tables.

        Idempotent safety net that runs after create_all() to guarantee
        RLS is active even if Alembic migrations were skipped.
        Uses PL/pgSQL DO blocks so missing tables are silently skipped.
        """
        if _engine is None:
            return

        # Tables with standard tenant_id column
        _std = [
            "conversations", "messages", "sessions", "audit_log",
            "alert_history", "investigations", "app_config",
            "notification_channel_configs", "token_usage",
            "alert_acknowledgments", "alert_rule_mutes",
            "webhook_configs", "team_members", "team_invitations",
            "subscriptions", "tenant_llm_configs", "service_configs",
            "escalation_policies", "slack_installations",
            "usage_notifications", "event_quota_usage",
        ]

        try:
            async with _engine.begin() as conn:
                # -- Create non-superuser role for RLS enforcement.
                # Superusers bypass RLS, so application queries use
                # SET LOCAL ROLE argus_app to drop privileges per-tx.
                await conn.execute(text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'argus_app') "
                    "THEN CREATE ROLE argus_app NOLOGIN; END IF; "
                    "END $$"
                ))
                await conn.execute(text(
                    "GRANT USAGE ON SCHEMA public TO argus_app"
                ))
                await conn.execute(text(
                    "GRANT ALL ON ALL TABLES IN SCHEMA public TO argus_app"
                ))
                await conn.execute(text(
                    "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO argus_app"
                ))
                await conn.execute(text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT ALL ON TABLES TO argus_app"
                ))
                await conn.execute(text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT ALL ON SEQUENCES TO argus_app"
                ))

                # -- Standard tenant_id tables (skips missing)
                tables_arr = ", ".join(f"'{t}'" for t in _std)
                await conn.execute(text(
                    f"DO $$ DECLARE t text; BEGIN "
                    f"FOR t IN SELECT unnest(ARRAY[{tables_arr}]) LOOP "
                    f"IF EXISTS (SELECT 1 FROM information_schema.tables "
                    f"WHERE table_schema='public' AND table_name=t) THEN "
                    f"EXECUTE format("
                    f"'ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);"
                    f"EXECUTE format("
                    f"'ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);"
                    f"EXECUTE format("
                    f"'DROP POLICY IF EXISTS tenant_isolation ON %I',t);"
                    f"EXECUTE format("
                    f"'CREATE POLICY tenant_isolation ON %I "
                    f"USING (tenant_id = current_setting("
                    f"''app.current_tenant'', true)) "
                    f"WITH CHECK (tenant_id = current_setting("
                    f"''app.current_tenant'', true))',t);"
                    f"END IF; END LOOP; END $$"
                ))

                # -- tenants: uses `id` instead of tenant_id
                await conn.execute(text("""
                    DO $$ BEGIN
                        ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
                        ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
                        DROP POLICY IF EXISTS tenant_isolation ON tenants;
                        CREATE POLICY tenant_isolation ON tenants
                            USING (id = current_setting('app.current_tenant', true))
                            WITH CHECK (id = current_setting('app.current_tenant', true));
                    END $$
                """))

                # -- users: global identity — visible via team_members
                await conn.execute(text("""
                    DO $$ BEGIN
                        ALTER TABLE users ENABLE ROW LEVEL SECURITY;
                        ALTER TABLE users FORCE ROW LEVEL SECURITY;
                        DROP POLICY IF EXISTS tenant_isolation ON users;
                        DROP POLICY IF EXISTS user_read ON users;
                        DROP POLICY IF EXISTS user_write ON users;
                        DROP POLICY IF EXISTS user_modify ON users;
                        DROP POLICY IF EXISTS user_delete ON users;
                        CREATE POLICY user_read ON users FOR SELECT
                            USING (id IN (
                                SELECT user_id FROM team_members
                                WHERE tenant_id = current_setting('app.current_tenant', true)
                            ));
                        CREATE POLICY user_write ON users FOR INSERT
                            WITH CHECK (true);
                        CREATE POLICY user_modify ON users FOR UPDATE
                            USING (true) WITH CHECK (true);
                        CREATE POLICY user_delete ON users FOR DELETE
                            USING (true);
                    END $$
                """))

                # -- api_keys: dual policies (tenant + key lookup)
                await conn.execute(text("""
                    DO $$ BEGIN
                        ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
                        ALTER TABLE api_keys FORCE ROW LEVEL SECURITY;
                        DROP POLICY IF EXISTS tenant_isolation ON api_keys;
                        DROP POLICY IF EXISTS api_key_lookup ON api_keys;
                        CREATE POLICY tenant_isolation ON api_keys
                            USING (tenant_id = current_setting('app.current_tenant', true))
                            WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
                        CREATE POLICY api_key_lookup ON api_keys FOR SELECT
                            USING (current_setting('app.current_tenant', true) = '' OR
                                   tenant_id = current_setting('app.current_tenant', true));
                    END $$
                """))

                # -- Token tables: user_id via team_members
                await conn.execute(text(
                    "DO $$ DECLARE t text; BEGIN "
                    "FOR t IN SELECT unnest(ARRAY["
                    "'email_verification_tokens',"
                    "'password_reset_tokens']) LOOP "
                    "IF EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name=t) THEN "
                    "EXECUTE format("
                    "'ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);"
                    "EXECUTE format("
                    "'ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);"
                    "EXECUTE format("
                    "'DROP POLICY IF EXISTS tenant_isolation ON %I',t);"
                    "EXECUTE format("
                    "'CREATE POLICY tenant_isolation ON %I "
                    "USING (user_id IN ("
                    "SELECT user_id FROM team_members "
                    "WHERE tenant_id = current_setting("
                    "''app.current_tenant'', true)))',t);"
                    "END IF; END LOOP; END $$"
                ))

            logger.info("RLS policies ensured on all tables")
        except Exception:
            logger.warning("Failed to ensure RLS policies", exc_info=True)
