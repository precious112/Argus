"""DuckDB time-series storage for metrics, log index, and SDK events."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger("argus.timeseries")

_conn: duckdb.DuckDBPyConnection | None = None


def init_timeseries(db_path: str) -> None:
    """Initialize DuckDB and create time-series tables."""
    global _conn

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _conn = duckdb.connect(db_path)

    _conn.execute("""
        CREATE TABLE IF NOT EXISTS system_metrics (
            timestamp TIMESTAMP NOT NULL,
            metric_name VARCHAR NOT NULL,
            value DOUBLE NOT NULL,
            labels JSON,
        )
    """)

    _conn.execute("""
        CREATE TABLE IF NOT EXISTS log_index (
            timestamp TIMESTAMP NOT NULL,
            file_path VARCHAR NOT NULL,
            line_offset BIGINT NOT NULL,
            severity VARCHAR,
            message_preview VARCHAR,
            source VARCHAR,
        )
    """)

    _conn.execute("""
        CREATE TABLE IF NOT EXISTS sdk_events (
            timestamp TIMESTAMP NOT NULL,
            service VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL,
            data JSON,
        )
    """)

    # Create indexes for common query patterns
    _conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_metrics_ts
        ON system_metrics (timestamp, metric_name)
    """)
    _conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_ts
        ON log_index (timestamp, severity)
    """)
    _conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sdk_ts
        ON sdk_events (timestamp, service, event_type)
    """)

    logger.info("DuckDB time-series store initialized at %s", db_path)


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get the DuckDB connection."""
    if _conn is None:
        raise RuntimeError("Time-series store not initialized. Call init_timeseries() first.")
    return _conn


def close_timeseries() -> None:
    """Close the DuckDB connection."""
    global _conn
    if _conn:
        _conn.close()
        _conn = None
