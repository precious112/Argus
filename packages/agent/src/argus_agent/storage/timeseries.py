"""DuckDB time-series storage for metrics, log index, and SDK events."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

    _conn.execute("""
        CREATE TABLE IF NOT EXISTS metric_baselines (
            updated_at TIMESTAMP NOT NULL,
            metric_name VARCHAR NOT NULL,
            mean DOUBLE NOT NULL,
            stddev DOUBLE NOT NULL,
            min_val DOUBLE NOT NULL,
            max_val DOUBLE NOT NULL,
            p50 DOUBLE NOT NULL,
            p95 DOUBLE NOT NULL,
            p99 DOUBLE NOT NULL,
            sample_count INTEGER NOT NULL,
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


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def insert_metric(
    metric_name: str,
    value: float,
    labels: dict[str, str] | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Insert a single metric data point."""
    conn = get_connection()
    ts = timestamp or datetime.now(UTC)
    conn.execute(
        "INSERT INTO system_metrics VALUES (?, ?, ?, ?)",
        [ts, metric_name, value, json.dumps(labels or {})],
    )


def insert_metrics_batch(
    rows: list[tuple[datetime, str, float, dict[str, str] | None]],
) -> None:
    """Insert multiple metric data points in a single batch."""
    if not rows:
        return
    conn = get_connection()
    prepared = [(ts, name, val, json.dumps(labels or {})) for ts, name, val, labels in rows]
    conn.executemany("INSERT INTO system_metrics VALUES (?, ?, ?, ?)", prepared)


def insert_log_entry(
    file_path: str,
    line_offset: int,
    severity: str = "",
    message_preview: str = "",
    source: str = "",
    timestamp: datetime | None = None,
) -> None:
    """Insert a log index entry."""
    conn = get_connection()
    ts = timestamp or datetime.now(UTC)
    conn.execute(
        "INSERT INTO log_index VALUES (?, ?, ?, ?, ?, ?)",
        [ts, file_path, line_offset, severity, message_preview[:200], source],
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def query_metrics(
    metric_name: str,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Query metric time-series data points."""
    conn = get_connection()
    conditions = ["metric_name = ?"]
    params: list[Any] = [metric_name]

    if since:
        conditions.append("timestamp >= ?")
        params.append(since)
    if until:
        conditions.append("timestamp <= ?")
        params.append(until)

    where = " AND ".join(conditions)
    params.append(limit)
    result = conn.execute(
        f"SELECT timestamp, metric_name, value, labels FROM system_metrics "  # noqa: S608
        f"WHERE {where} ORDER BY timestamp DESC LIMIT ?",
        params,
    ).fetchall()

    return [
        {
            "timestamp": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
            "metric_name": row[1],
            "value": row[2],
            "labels": json.loads(row[3]) if isinstance(row[3], str) else row[3],
        }
        for row in result
    ]


def query_metrics_summary(
    metric_name: str,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Get aggregate statistics for a metric."""
    conn = get_connection()
    conditions = ["metric_name = ?"]
    params: list[Any] = [metric_name]

    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    where = " AND ".join(conditions)
    result = conn.execute(
        f"SELECT MIN(value), MAX(value), AVG(value), COUNT(*) "  # noqa: S608
        f"FROM system_metrics WHERE {where}",
        params,
    ).fetchone()

    if not result or result[3] == 0:
        return {"metric_name": metric_name, "count": 0}

    return {
        "metric_name": metric_name,
        "min": result[0],
        "max": result[1],
        "avg": round(result[2], 2),
        "count": result[3],
    }


def query_latest_metrics() -> dict[str, float]:
    """Get the most recent value for each metric name."""
    conn = get_connection()
    result = conn.execute("""
        SELECT metric_name, value
        FROM system_metrics
        WHERE timestamp = (
            SELECT MAX(timestamp) FROM system_metrics s2
            WHERE s2.metric_name = system_metrics.metric_name
        )
    """).fetchall()
    return {row[0]: row[1] for row in result}


def query_log_entries(
    severity: str | None = None,
    file_path: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query the log index."""
    conn = get_connection()
    conditions: list[str] = []
    params: list[Any] = []

    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if file_path:
        conditions.append("file_path = ?")
        params.append(file_path)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    result = conn.execute(
        f"SELECT timestamp, file_path, line_offset, severity, message_preview, source "  # noqa: S608
        f"FROM log_index{where} ORDER BY timestamp DESC LIMIT ?",
        params,
    ).fetchall()

    return [
        {
            "timestamp": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
            "file_path": row[1],
            "line_offset": row[2],
            "severity": row[3],
            "message_preview": row[4],
            "source": row[5],
        }
        for row in result
    ]
