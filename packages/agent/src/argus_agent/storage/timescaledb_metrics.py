"""TimescaleDB implementation of MetricsRepository (SaaS mode).

Uses raw asyncpg pool for performance on bulk inserts.  Protocol methods
are sync (matching DuckDB interface); internal methods are async with a
sync-to-async bridge via ``asyncio.get_event_loop().run_until_complete()``.

Tenant isolation is handled by PostgreSQL RLS — every connection does
``SET LOCAL app.current_tenant`` before executing queries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("argus.storage.timescaledb")

_RE_JSON_EXTRACT = re.compile(
    r"json_extract_string\(\s*(\w+)\s*,\s*'\$\.(\w+)'\s*\)"
)
_RE_CAST_JSON_DOUBLE = re.compile(
    r"CAST\(\s*json_extract_string\(\s*(\w+)\s*,\s*'\$\.(\w+)'\s*\)\s*AS\s+DOUBLE\s*\)"
)


def _duckdb_to_pg(sql: str) -> str:
    """Convert DuckDB-specific SQL patterns to PostgreSQL/TimescaleDB."""
    # CAST(json_extract_string(col, '$.key') AS DOUBLE) → (col->>'key')::double precision
    sql = _RE_CAST_JSON_DOUBLE.sub(r"(\1->>'\2')::double precision", sql)
    # json_extract_string(col, '$.key') → col->>'key'
    sql = _RE_JSON_EXTRACT.sub(r"\1->>'\2'", sql)
    return sql


def _rewrite_placeholders(sql: str, params: list[Any] | None) -> tuple[str, list[Any] | None]:
    """Rewrite ``?`` positional placeholders to ``$1, $2, ...`` for asyncpg."""
    if params is None:
        return sql, None
    idx = 0
    parts: list[str] = []
    i = 0
    while i < len(sql):
        if sql[i] == "?" and not _in_string(sql, i):
            idx += 1
            parts.append(f"${idx}")
        else:
            parts.append(sql[i])
        i += 1
    return "".join(parts), params


def _in_string(sql: str, pos: int) -> bool:
    """Check whether position *pos* is inside a single-quoted string literal."""
    count = 0
    for i in range(pos):
        if sql[i] == "'" and (i == 0 or sql[i - 1] != "\\"):
            count += 1
    return count % 2 == 1


def _ts_str(val: Any) -> str:
    """Format a value as an ISO timestamp string."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


class TimescaleDBMetricsRepository:
    """MetricsRepository backed by TimescaleDB (SaaS mode).

    Uses a raw asyncpg connection pool for performance on bulk inserts and
    complex analytical queries.
    """

    def __init__(self) -> None:
        self._url: str = ""
        self._pool: Any = None  # asyncpg.Pool (created lazily)

    # --- Lifecycle ---

    def init(self, db_url: str) -> None:
        """Store the connection URL. Pool is created lazily on first use."""
        self._url = db_url
        logger.info("TimescaleDB metrics repository configured (lazy pool)")

    def close(self) -> None:
        if self._pool is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._pool.close())
                else:
                    loop.run_until_complete(self._pool.close())
            except Exception:
                logger.warning("Failed to close TimescaleDB pool", exc_info=True)
            self._pool = None

    async def _get_pool(self) -> Any:
        """Lazily create the asyncpg pool and run schema setup."""
        if self._pool is None:
            import asyncpg

            url = self._url
            # Strip SQLAlchemy driver prefix if present
            if "+asyncpg" in url:
                url = url.replace("postgresql+asyncpg://", "postgresql://")
            self._pool = await asyncpg.create_pool(url, min_size=5, max_size=25)
            await self._apply_schema()
        return self._pool

    async def _apply_schema(self) -> None:
        """Run the TimescaleDB schema SQL."""
        try:
            schema_path = Path(__file__).parent / "timescale_schema.sql"
            sql = schema_path.read_text()
            pool = self._pool
            async with pool.acquire() as conn:
                await conn.execute(sql)
            logger.info("TimescaleDB schema applied")
        except Exception:
            logger.warning("TimescaleDB schema application failed (non-fatal)", exc_info=True)

    def _run(self, coro: Any) -> Any:
        """Sync-to-async bridge."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result(timeout=30)
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    async def _execute(self, query: str, params: list[Any] | None = None) -> list[Any]:
        """Execute a query with RLS tenant context and return rows."""
        from argus_agent.tenancy.context import get_tenant_id

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            tenant_id = get_tenant_id()
            await conn.execute("SET LOCAL app.current_tenant = $1", tenant_id)
            if params:
                return await conn.fetch(query, *params)
            return await conn.fetch(query)

    async def _execute_void(self, query: str, params: list[Any] | None = None) -> None:
        """Execute a query that returns no rows."""
        from argus_agent.tenancy.context import get_tenant_id

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            tenant_id = get_tenant_id()
            await conn.execute("SET LOCAL app.current_tenant = $1", tenant_id)
            if params:
                await conn.execute(query, *params)
            else:
                await conn.execute(query)

    # --- System Metrics ---

    def insert_metric(
        self,
        metric_name: str,
        value: float,
        labels: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        from argus_agent.tenancy.context import get_tenant_id

        ts = timestamp or datetime.now(UTC)
        tid = get_tenant_id()
        self._run(self._execute_void(
            "INSERT INTO system_metrics (timestamp, tenant_id, metric_name, value, labels) "
            "VALUES ($1, $2, $3, $4, $5)",
            [ts, tid, metric_name, value, json.dumps(labels or {})],
        ))

    def insert_metrics_batch(
        self,
        rows: list[tuple[datetime, str, float, dict[str, str] | None]],
    ) -> None:
        if not rows:
            return
        from argus_agent.tenancy.context import get_tenant_id

        tid = get_tenant_id()

        async def _batch() -> None:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("SET LOCAL app.current_tenant = $1", tid)
                await conn.executemany(
                    "INSERT INTO system_metrics (timestamp, tenant_id, metric_name, value, labels) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    [
                        (ts, tid, name, val, json.dumps(labels or {}))
                        for ts, name, val, labels in rows
                    ],
                )

        self._run(_batch())

    def query_metrics(
        self,
        metric_name: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        conditions = ["metric_name = $1"]
        params: list[Any] = [metric_name]
        idx = 1

        if since:
            idx += 1
            conditions.append(f"timestamp >= ${idx}")
            params.append(since)
        if until:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until)

        idx += 1
        where = " AND ".join(conditions)
        query = (
            f"SELECT timestamp, metric_name, value, labels FROM system_metrics "
            f"WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}"
        )
        params.append(limit)

        rows = self._run(self._execute(query, params))
        return [
            {
                "timestamp": _ts_str(r["timestamp"]),
                "metric_name": r["metric_name"],
                "value": r["value"],
                "labels": json.loads(r["labels"]) if isinstance(r["labels"], str) else r["labels"],
            }
            for r in rows
        ]

    def query_metrics_summary(
        self,
        metric_name: str,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        conditions = ["metric_name = $1"]
        params: list[Any] = [metric_name]

        if since:
            conditions.append("timestamp >= $2")
            params.append(since)

        where = " AND ".join(conditions)
        rows = self._run(self._execute(
            f"SELECT MIN(value), MAX(value), AVG(value), COUNT(*) "
            f"FROM system_metrics WHERE {where}",
            params,
        ))
        if not rows or rows[0]["count"] == 0:
            return {"metric_name": metric_name, "count": 0}

        r = rows[0]
        return {
            "metric_name": metric_name,
            "min": r["min"],
            "max": r["max"],
            "avg": round(float(r["avg"]), 2),
            "count": r["count"],
        }

    def query_latest_metrics(self) -> dict[str, float]:
        rows = self._run(self._execute(
            "SELECT DISTINCT ON (metric_name) metric_name, value "
            "FROM system_metrics ORDER BY metric_name, timestamp DESC"
        ))
        return {r["metric_name"]: r["value"] for r in rows}

    # --- Log Index ---

    def insert_log_entry(
        self,
        file_path: str,
        line_offset: int,
        severity: str = "",
        message_preview: str = "",
        source: str = "",
        timestamp: datetime | None = None,
    ) -> None:
        from argus_agent.tenancy.context import get_tenant_id

        ts = timestamp or datetime.now(UTC)
        tid = get_tenant_id()
        self._run(self._execute_void(
            "INSERT INTO log_index (timestamp, tenant_id, file_path, line_offset, severity, "
            "message_preview, source) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            [ts, tid, file_path, line_offset, severity, message_preview[:200], source],
        ))

    def query_log_entries(
        self,
        severity: str | None = None,
        file_path: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        idx = 0

        if severity:
            idx += 1
            conditions.append(f"severity = ${idx}")
            params.append(severity)
        if file_path:
            idx += 1
            conditions.append(f"file_path = ${idx}")
            params.append(file_path)
        if since:
            idx += 1
            conditions.append(f"timestamp >= ${idx}")
            params.append(since)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        idx += 1
        rows = self._run(self._execute(
            f"SELECT timestamp, file_path, line_offset, severity, message_preview, source "
            f"FROM log_index{where} ORDER BY timestamp DESC LIMIT ${idx}",
            params + [limit],
        ))

        return [
            {
                "timestamp": _ts_str(r["timestamp"]),
                "file_path": r["file_path"],
                "line_offset": r["line_offset"],
                "severity": r["severity"],
                "message_preview": r["message_preview"],
                "source": r["source"],
            }
            for r in rows
        ]

    # --- SDK Events ---

    def insert_sdk_event(
        self,
        timestamp: datetime,
        service: str,
        event_type: str,
        data: str,
    ) -> None:
        from argus_agent.tenancy.context import get_tenant_id

        tid = get_tenant_id()
        # data comes as a JSON string from callers — store as JSONB
        self._run(self._execute_void(
            "INSERT INTO sdk_events (timestamp, tenant_id, service, event_type, data) "
            "VALUES ($1, $2, $3, $4, $5::jsonb)",
            [timestamp, tid, service, event_type, data],
        ))

    def query_service_summary(
        self,
        service: str = "",
        since_minutes: int = 1440,
    ) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1"]
        params: list[Any] = [since]
        idx = 1

        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)

        where = " AND ".join(conditions)
        rows = self._run(self._execute(
            f"SELECT service, COUNT(*) AS event_count, "
            f"COUNT(DISTINCT event_type) AS event_type_count, "
            f"COUNT(*) FILTER (WHERE event_type = 'exception') AS error_count, "
            f"COUNT(*) FILTER (WHERE event_type = 'invocation_end') AS invocation_count, "
            f"MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen "
            f"FROM sdk_events WHERE {where} GROUP BY service ORDER BY event_count DESC",
            params,
        ))
        return [
            {
                "service": r["service"],
                "event_count": r["event_count"],
                "event_type_count": r["event_type_count"],
                "error_count": r["error_count"],
                "invocation_count": r["invocation_count"],
                "first_seen": _ts_str(r["first_seen"]),
                "last_seen": _ts_str(r["last_seen"]),
            }
            for r in rows
        ]

    def query_error_groups(
        self,
        service: str = "",
        since_minutes: int = 1440,
        limit: int = 20,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1", "event_type = 'exception'"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)
        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)

        where = " AND ".join(conditions)
        idx += 1
        rows = self._run(self._execute(
            f"SELECT data->>'type' AS error_type, data->>'message' AS error_message, "
            f"COUNT(*) AS count, MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen, "
            f"service FROM sdk_events WHERE {where} "
            f"GROUP BY error_type, error_message, service ORDER BY count DESC LIMIT ${idx}",
            params + [limit],
        ))
        return [
            {
                "error_type": r["error_type"] or "Unknown",
                "error_message": (r["error_message"] or "")[:200],
                "count": r["count"],
                "first_seen": _ts_str(r["first_seen"]),
                "last_seen": _ts_str(r["last_seen"]),
                "service": r["service"],
            }
            for r in rows
        ]

    def query_function_metrics(
        self,
        service: str = "",
        function_name: str = "",
        since_minutes: int = 60,
        interval_minutes: int = 5,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1", "event_type IN ('invocation_start', 'invocation_end')"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)
        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)

        where = " AND ".join(conditions)
        query = f"""
            SELECT
                time_bucket('{interval_minutes} minutes'::interval, timestamp) AS bucket,
                COUNT(*) FILTER (WHERE event_type = 'invocation_end') AS invocation_count,
                COUNT(*) FILTER (WHERE event_type = 'invocation_end'
                    AND data->>'status' != 'ok') AS error_count,
                COALESCE(AVG((data->>'duration_ms')::double precision)
                    FILTER (WHERE event_type = 'invocation_end'), 0) AS avg_duration,
                COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                    (ORDER BY (data->>'duration_ms')::double precision)
                    FILTER (WHERE event_type = 'invocation_end'), 0) AS p50_duration,
                COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP
                    (ORDER BY (data->>'duration_ms')::double precision)
                    FILTER (WHERE event_type = 'invocation_end'), 0) AS p95_duration,
                COALESCE(PERCENTILE_CONT(0.99) WITHIN GROUP
                    (ORDER BY (data->>'duration_ms')::double precision)
                    FILTER (WHERE event_type = 'invocation_end'), 0) AS p99_duration,
                COUNT(*) FILTER (WHERE event_type = 'invocation_start'
                    AND data->>'is_cold_start' = 'true') AS cold_start_count,
                COUNT(*) FILTER (WHERE event_type = 'invocation_start') AS start_count
            FROM sdk_events
            WHERE {where}
            GROUP BY bucket
            ORDER BY bucket
        """

        try:
            rows = self._run(self._execute(query, params))
        except Exception:
            logger.exception("Failed to query function metrics")
            return []

        buckets = []
        for r in rows:
            inv = r["invocation_count"] or 0
            errs = r["error_count"] or 0
            starts = r["start_count"] or 0
            colds = r["cold_start_count"] or 0
            buckets.append({
                "bucket": _ts_str(r["bucket"]),
                "invocation_count": inv,
                "error_count": errs,
                "error_rate": round(errs / inv * 100, 1) if inv > 0 else 0,
                "avg_duration_ms": round(float(r["avg_duration"]), 2),
                "p50_duration_ms": round(float(r["p50_duration"]), 2),
                "p95_duration_ms": round(float(r["p95_duration"]), 2),
                "p99_duration_ms": round(float(r["p99_duration"]), 2),
                "cold_start_count": colds,
                "cold_start_pct": round(colds / starts * 100, 1) if starts > 0 else 0,
            })
        return buckets

    # --- Spans / Traces ---

    def insert_span(
        self,
        trace_id: str,
        span_id: str,
        service: str,
        name: str,
        kind: str,
        *,
        parent_span_id: str | None = None,
        duration_ms: float | None = None,
        status: str = "ok",
        error_type: str | None = None,
        error_message: str | None = None,
        data: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        from argus_agent.tenancy.context import get_tenant_id

        ts = timestamp or datetime.now(UTC)
        tid = get_tenant_id()
        self._run(self._execute_void(
            "INSERT INTO spans (timestamp, tenant_id, trace_id, span_id, parent_span_id, "
            "service, name, kind, duration_ms, status, error_type, error_message, data) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)",
            [ts, tid, trace_id, span_id, parent_span_id, service, name, kind,
             duration_ms, status, error_type, error_message, json.dumps(data or {})],
        ))

    def query_trace(self, trace_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._run(self._execute(
            "SELECT timestamp, trace_id, span_id, parent_span_id, service, name, "
            "kind, duration_ms, status, error_type, error_message, data "
            "FROM spans WHERE trace_id = $1 ORDER BY timestamp LIMIT $2",
            [trace_id, limit],
        ))
        return [
            {
                "timestamp": _ts_str(r["timestamp"]),
                "trace_id": r["trace_id"],
                "span_id": r["span_id"],
                "parent_span_id": r["parent_span_id"],
                "service": r["service"],
                "name": r["name"],
                "kind": r["kind"],
                "duration_ms": r["duration_ms"],
                "status": r["status"],
                "error_type": r["error_type"],
                "error_message": r["error_message"],
                "data": r["data"] if isinstance(r["data"], dict) else json.loads(r["data"] or "{}"),
            }
            for r in rows
        ]

    def query_slow_spans(
        self,
        service: str = "",
        since_minutes: int = 60,
        limit: int = 20,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1", "duration_ms IS NOT NULL"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)
        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)

        where = " AND ".join(conditions)
        idx += 1
        rows = self._run(self._execute(
            f"SELECT timestamp, trace_id, span_id, service, name, kind, "
            f"duration_ms, status, error_type "
            f"FROM spans WHERE {where} ORDER BY duration_ms DESC LIMIT ${idx}",
            params + [limit],
        ))
        return [
            {
                "timestamp": _ts_str(r["timestamp"]),
                "trace_id": r["trace_id"],
                "span_id": r["span_id"],
                "service": r["service"],
                "name": r["name"],
                "kind": r["kind"],
                "duration_ms": r["duration_ms"],
                "status": r["status"],
                "error_type": r["error_type"],
            }
            for r in rows
        ]

    def query_trace_summary(
        self,
        service: str = "",
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1", "duration_ms IS NOT NULL"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)
        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)

        where = " AND ".join(conditions)

        try:
            rows = self._run(self._execute(
                f"SELECT service, name, kind, COUNT(*) AS cnt, "
                f"AVG(duration_ms) AS avg_ms, "
                f"PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50, "
                f"PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95, "
                f"PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99, "
                f"COUNT(*) FILTER (WHERE status != 'ok') AS error_count "
                f"FROM spans WHERE {where} GROUP BY service, name, kind ORDER BY avg_ms DESC",
                params,
            ))
        except Exception:
            logger.exception("Failed to query trace summary")
            return []

        return [
            {
                "service": r["service"],
                "name": r["name"],
                "kind": r["kind"],
                "count": r["cnt"],
                "avg_ms": round(float(r["avg_ms"]), 2),
                "p50_ms": round(float(r["p50"]), 2),
                "p95_ms": round(float(r["p95"]), 2),
                "p99_ms": round(float(r["p99"]), 2),
                "error_count": r["error_count"],
            }
            for r in rows
        ]

    def query_request_metrics(
        self,
        service: str = "",
        path: str = "",
        method: str = "",
        since_minutes: int = 60,
        interval_minutes: int = 5,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1", "kind = 'server'", "duration_ms IS NOT NULL"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)
        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)
        if path:
            idx += 1
            conditions.append(f"data->>'path' = ${idx}")
            params.append(path)
        if method:
            idx += 1
            conditions.append(f"data->>'method' = ${idx}")
            params.append(method)

        where = " AND ".join(conditions)
        query = f"""
            SELECT
                time_bucket('{interval_minutes} minutes'::interval, timestamp) AS bucket,
                COUNT(*) AS request_count,
                COUNT(*) FILTER (WHERE status != 'ok') AS error_count,
                AVG(duration_ms) AS avg_ms,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99
            FROM spans
            WHERE {where}
            GROUP BY bucket
            ORDER BY bucket
        """

        try:
            rows = self._run(self._execute(query, params))
        except Exception:
            logger.exception("Failed to query request metrics")
            return []

        return [
            {
                "bucket": _ts_str(r["bucket"]),
                "request_count": r["request_count"],
                "error_count": r["error_count"],
                "error_rate": round(r["error_count"] / r["request_count"] * 100, 1)
                if r["request_count"] > 0 else 0,
                "avg_ms": round(float(r["avg_ms"]), 2),
                "p50_ms": round(float(r["p50"]), 2),
                "p95_ms": round(float(r["p95"]), 2),
                "p99_ms": round(float(r["p99"]), 2),
            }
            for r in rows
        ]

    # --- SDK Metrics ---

    def insert_sdk_metric(
        self,
        service: str,
        metric_name: str,
        value: float,
        labels: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        from argus_agent.tenancy.context import get_tenant_id

        ts = timestamp or datetime.now(UTC)
        tid = get_tenant_id()
        self._run(self._execute_void(
            "INSERT INTO sdk_metrics (timestamp, tenant_id, service, metric_name, value, labels) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            [ts, tid, service, metric_name, value, json.dumps(labels or {})],
        ))

    def query_sdk_metrics(
        self,
        service: str = "",
        metric_name: str = "",
        since_minutes: int = 60,
        limit: int = 500,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)
        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)
        if metric_name:
            idx += 1
            conditions.append(f"metric_name = ${idx}")
            params.append(metric_name)

        where = " AND ".join(conditions)
        idx += 1
        rows = self._run(self._execute(
            f"SELECT timestamp, service, metric_name, value, labels "
            f"FROM sdk_metrics WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}",
            params + [limit],
        ))
        return [
            {
                "timestamp": _ts_str(r["timestamp"]),
                "service": r["service"],
                "metric_name": r["metric_name"],
                "value": r["value"],
                "labels": (
                    r["labels"] if isinstance(r["labels"], dict)
                    else json.loads(r["labels"] or "{}")
                ),
            }
            for r in rows
        ]

    # --- Dependency Calls ---

    def insert_dependency_call(
        self,
        service: str,
        dep_type: str,
        target: str,
        *,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        operation: str = "",
        duration_ms: float | None = None,
        status: str = "ok",
        status_code: int | None = None,
        error_message: str | None = None,
        data: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        from argus_agent.tenancy.context import get_tenant_id

        ts = timestamp or datetime.now(UTC)
        tid = get_tenant_id()
        self._run(self._execute_void(
            "INSERT INTO dependency_calls (timestamp, tenant_id, service, dep_type, target, "
            "trace_id, span_id, parent_span_id, operation, duration_ms, status, status_code, "
            "error_message, data) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)",
            [ts, tid, service, dep_type, target, trace_id, span_id, parent_span_id,
             operation, duration_ms, status, status_code, error_message,
             json.dumps(data or {})],
        ))

    def query_dependencies(
        self,
        service: str = "",
        dep_type: str = "",
        since_minutes: int = 60,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1"]
        params: list[Any] = [since]
        idx = 1

        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)
        if dep_type:
            idx += 1
            conditions.append(f"dep_type = ${idx}")
            params.append(dep_type)

        where = " AND ".join(conditions)
        idx += 1
        rows = self._run(self._execute(
            f"SELECT timestamp, trace_id, span_id, service, dep_type, target, "
            f"operation, duration_ms, status, status_code, error_message "
            f"FROM dependency_calls WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}",
            params + [limit],
        ))
        return [
            {
                "timestamp": _ts_str(r["timestamp"]),
                "trace_id": r["trace_id"],
                "span_id": r["span_id"],
                "service": r["service"],
                "dep_type": r["dep_type"],
                "target": r["target"],
                "operation": r["operation"],
                "duration_ms": r["duration_ms"],
                "status": r["status"],
                "status_code": r["status_code"],
                "error_message": r["error_message"],
            }
            for r in rows
        ]

    def query_dependency_summary(
        self,
        service: str = "",
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)
        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)

        where = " AND ".join(conditions)

        try:
            rows = self._run(self._execute(
                f"SELECT dep_type, target, COUNT(*) AS cnt, "
                f"AVG(duration_ms) AS avg_ms, "
                f"PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50, "
                f"PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95, "
                f"COUNT(*) FILTER (WHERE status != 'ok') AS error_count "
                f"FROM dependency_calls WHERE {where} "
                f"GROUP BY dep_type, target ORDER BY cnt DESC",
                params,
            ))
        except Exception:
            logger.exception("Failed to query dependency summary")
            return []

        return [
            {
                "dep_type": r["dep_type"],
                "target": r["target"],
                "count": r["cnt"],
                "avg_ms": round(float(r["avg_ms"]), 2) if r["avg_ms"] else 0,
                "p50_ms": round(float(r["p50"]), 2) if r["p50"] else 0,
                "p95_ms": round(float(r["p95"]), 2) if r["p95"] else 0,
                "error_count": r["error_count"],
                "error_rate": round(r["error_count"] / r["cnt"] * 100, 1) if r["cnt"] > 0 else 0,
            }
            for r in rows
        ]

    def query_dependency_map(
        self,
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)

        where = " AND ".join(conditions)
        rows = self._run(self._execute(
            f"SELECT service, dep_type, target, COUNT(*) AS cnt "
            f"FROM dependency_calls WHERE {where} "
            f"GROUP BY service, dep_type, target ORDER BY cnt DESC",
            params,
        ))
        return [
            {"service": r["service"], "dep_type": r["dep_type"],
             "target": r["target"], "call_count": r["cnt"]}
            for r in rows
        ]

    # --- Deploy Events ---

    def insert_deploy_event(
        self,
        service: str,
        *,
        version: str = "",
        git_sha: str = "",
        environment: str = "",
        previous_version: str = "",
        data: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        from argus_agent.tenancy.context import get_tenant_id

        ts = timestamp or datetime.now(UTC)
        tid = get_tenant_id()
        self._run(self._execute_void(
            "INSERT INTO deploy_events (timestamp, tenant_id, service, version, git_sha, "
            "environment, previous_version, data) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)",
            [ts, tid, service, version, git_sha, environment, previous_version,
             json.dumps(data or {})],
        ))

    def query_deploy_history(
        self,
        service: str = "",
        since_minutes: int = 10080,
        limit: int = 50,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        since = since_dt if since_dt else datetime.now(UTC) - timedelta(minutes=since_minutes)
        conditions = ["timestamp >= $1"]
        params: list[Any] = [since]
        idx = 1

        if until_dt:
            idx += 1
            conditions.append(f"timestamp <= ${idx}")
            params.append(until_dt)
        if service:
            idx += 1
            conditions.append(f"service = ${idx}")
            params.append(service)

        where = " AND ".join(conditions)
        idx += 1
        rows = self._run(self._execute(
            f"SELECT timestamp, service, version, git_sha, environment, "
            f"previous_version, data FROM deploy_events WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT ${idx}",
            params + [limit],
        ))
        return [
            {
                "timestamp": _ts_str(r["timestamp"]),
                "service": r["service"],
                "version": r["version"],
                "git_sha": r["git_sha"],
                "environment": r["environment"],
                "previous_version": r["previous_version"],
                "data": r["data"] if isinstance(r["data"], dict) else json.loads(r["data"] or "{}"),
            }
            for r in rows
        ]

    def get_previous_deploy_version(self, service: str) -> str | None:
        rows = self._run(self._execute(
            "SELECT git_sha FROM deploy_events WHERE service = $1 "
            "ORDER BY timestamp DESC LIMIT 1",
            [service],
        ))
        return rows[0]["git_sha"] if rows else None

    # --- Error Fingerprinting ---

    def compute_error_fingerprint(self, error_type: str, traceback_str: str) -> str:
        lines = traceback_str.strip().splitlines()
        normalised: list[str] = []
        for line in lines:
            line = re.sub(r", line \d+", "", line)
            line = re.sub(
                r'File "([^"]+)"',
                lambda m: f'File "{os.path.basename(m.group(1))}"',
                line,
            )
            normalised.append(line.strip())
        raw = f"{error_type}:{'|'.join(normalised)}"
        return hashlib.md5(raw.encode()).hexdigest()  # noqa: S324

    # --- Raw Query Access ---

    def execute_raw(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Execute a raw SQL query.

        Converts DuckDB SQL patterns (json_extract_string, ? placeholders)
        to PostgreSQL equivalents automatically.
        """
        pg_sql = _duckdb_to_pg(query)
        pg_sql, pg_params = _rewrite_placeholders(pg_sql, params)

        async def _raw() -> list[tuple[Any, ...]]:
            from argus_agent.tenancy.context import get_tenant_id

            pool = await self._get_pool()
            async with pool.acquire() as conn:
                tenant_id = get_tenant_id()
                await conn.execute("SET LOCAL app.current_tenant = $1", tenant_id)
                if pg_params:
                    rows = await conn.fetch(pg_sql, *pg_params)
                else:
                    rows = await conn.fetch(pg_sql)
                return [tuple(r.values()) for r in rows]

        return self._run(_raw())
