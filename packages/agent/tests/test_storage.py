"""Tests for storage layer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from argus_agent.storage.database import close_db, get_session, init_db
from argus_agent.storage.models import Conversation
from argus_agent.storage.timeseries import close_timeseries, get_connection, init_timeseries


@pytest.mark.asyncio
async def test_sqlite_init_and_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        await init_db(db_path)

        async with get_session() as session:
            # Verify we can create and query records
            conv = Conversation(id="test-1", title="Test Conversation", source="user")
            session.add(conv)
            await session.commit()

        await close_db()


def test_duckdb_init_and_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.duckdb")
        init_timeseries(db_path)

        conn = get_connection()
        # Verify tables exist
        tables = conn.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]
        assert "system_metrics" in table_names
        assert "log_index" in table_names
        assert "sdk_events" in table_names

        close_timeseries()


def test_duckdb_insert_and_query():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.duckdb")
        init_timeseries(db_path)

        conn = get_connection()
        conn.execute("""
            INSERT INTO system_metrics (timestamp, metric_name, value, labels)
            VALUES (NOW(), 'cpu_percent', 45.2, '{"core": "all"}')
        """)

        result = conn.execute("SELECT COUNT(*) FROM system_metrics").fetchone()
        assert result[0] == 1

        close_timeseries()
