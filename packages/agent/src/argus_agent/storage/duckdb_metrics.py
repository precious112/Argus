"""DuckDB implementation of MetricsRepository.

Thin wrapper that delegates to the existing module-level functions in
``timeseries.py``.  This preserves backward compatibility while allowing
the SaaS mode to swap to a TimescaleDB implementation later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from argus_agent.storage import timeseries


class DuckDBMetricsRepository:
    """MetricsRepository backed by DuckDB (self-hosted mode)."""

    # --- Lifecycle ---

    def init(self, db_path: str) -> None:
        timeseries.init_timeseries(db_path)

    def close(self) -> None:
        timeseries.close_timeseries()

    # --- System Metrics ---

    def insert_metric(
        self,
        metric_name: str,
        value: float,
        labels: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        timeseries.insert_metric(metric_name, value, labels=labels, timestamp=timestamp)

    def insert_metrics_batch(
        self,
        rows: list[tuple[datetime, str, float, dict[str, str] | None]],
    ) -> None:
        timeseries.insert_metrics_batch(rows)

    def query_metrics(
        self,
        metric_name: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        return timeseries.query_metrics(metric_name, since=since, until=until, limit=limit)

    def query_metrics_summary(
        self,
        metric_name: str,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        return timeseries.query_metrics_summary(metric_name, since=since)

    def query_latest_metrics(self) -> dict[str, float]:
        return timeseries.query_latest_metrics()

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
        timeseries.insert_log_entry(
            file_path, line_offset,
            severity=severity, message_preview=message_preview,
            source=source, timestamp=timestamp,
        )

    def query_log_entries(
        self,
        severity: str | None = None,
        file_path: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return timeseries.query_log_entries(
            severity=severity, file_path=file_path, since=since, limit=limit,
        )

    # --- SDK Events ---

    def insert_sdk_event(
        self,
        timestamp: datetime,
        service: str,
        event_type: str,
        data: str,
    ) -> None:
        conn = timeseries.get_connection()
        conn.execute(
            "INSERT INTO sdk_events VALUES (?, ?, ?, ?)",
            [timestamp, service, event_type, data],
        )

    def query_service_summary(
        self,
        service: str = "",
        since_minutes: int = 1440,
    ) -> list[dict[str, Any]]:
        return timeseries.query_service_summary(service=service, since_minutes=since_minutes)

    def query_error_groups(
        self,
        service: str = "",
        since_minutes: int = 1440,
        limit: int = 20,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return timeseries.query_error_groups(
            service=service, since_minutes=since_minutes, limit=limit,
            since_dt=since_dt, until_dt=until_dt,
        )

    def query_function_metrics(
        self,
        service: str = "",
        function_name: str = "",
        since_minutes: int = 60,
        interval_minutes: int = 5,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return timeseries.query_function_metrics(
            service=service, function_name=function_name,
            since_minutes=since_minutes, interval_minutes=interval_minutes,
            since_dt=since_dt, until_dt=until_dt,
        )

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
        timeseries.insert_span(
            trace_id, span_id, service, name, kind,
            parent_span_id=parent_span_id, duration_ms=duration_ms,
            status=status, error_type=error_type, error_message=error_message,
            data=data, timestamp=timestamp,
        )

    def query_trace(
        self,
        trace_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return timeseries.query_trace(trace_id, limit=limit)

    def query_slow_spans(
        self,
        service: str = "",
        since_minutes: int = 60,
        limit: int = 20,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return timeseries.query_slow_spans(
            service=service, since_minutes=since_minutes, limit=limit,
            since_dt=since_dt, until_dt=until_dt,
        )

    def query_trace_summary(
        self,
        service: str = "",
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return timeseries.query_trace_summary(
            service=service, since_minutes=since_minutes,
            since_dt=since_dt, until_dt=until_dt,
        )

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
        return timeseries.query_request_metrics(
            service=service, path=path, method=method,
            since_minutes=since_minutes, interval_minutes=interval_minutes,
            since_dt=since_dt, until_dt=until_dt,
        )

    # --- SDK Metrics ---

    def insert_sdk_metric(
        self,
        service: str,
        metric_name: str,
        value: float,
        labels: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        timeseries.insert_sdk_metric(
            service, metric_name, value, labels=labels, timestamp=timestamp,
        )

    def query_sdk_metrics(
        self,
        service: str = "",
        metric_name: str = "",
        since_minutes: int = 60,
        limit: int = 500,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return timeseries.query_sdk_metrics(
            service=service, metric_name=metric_name,
            since_minutes=since_minutes, limit=limit,
            since_dt=since_dt, until_dt=until_dt,
        )

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
        timeseries.insert_dependency_call(
            service, dep_type, target,
            trace_id=trace_id, span_id=span_id, parent_span_id=parent_span_id,
            operation=operation, duration_ms=duration_ms, status=status,
            status_code=status_code, error_message=error_message,
            data=data, timestamp=timestamp,
        )

    def query_dependencies(
        self,
        service: str = "",
        dep_type: str = "",
        since_minutes: int = 60,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return timeseries.query_dependencies(
            service=service, dep_type=dep_type,
            since_minutes=since_minutes, limit=limit,
        )

    def query_dependency_summary(
        self,
        service: str = "",
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return timeseries.query_dependency_summary(
            service=service, since_minutes=since_minutes,
            since_dt=since_dt, until_dt=until_dt,
        )

    def query_dependency_map(
        self,
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return timeseries.query_dependency_map(
            since_minutes=since_minutes, since_dt=since_dt, until_dt=until_dt,
        )

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
        timeseries.insert_deploy_event(
            service, version=version, git_sha=git_sha,
            environment=environment, previous_version=previous_version,
            data=data, timestamp=timestamp,
        )

    def query_deploy_history(
        self,
        service: str = "",
        since_minutes: int = 10080,
        limit: int = 50,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return timeseries.query_deploy_history(
            service=service, since_minutes=since_minutes, limit=limit,
            since_dt=since_dt, until_dt=until_dt,
        )

    def get_previous_deploy_version(
        self,
        service: str,
    ) -> str | None:
        return timeseries.get_previous_deploy_version(service)

    # --- Error Fingerprinting ---

    def compute_error_fingerprint(
        self,
        error_type: str,
        traceback_str: str,
    ) -> str:
        return timeseries.compute_error_fingerprint(error_type, traceback_str)

    # --- Raw Query Access ---

    def execute_raw(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        conn = timeseries.get_connection()
        if params:
            return conn.execute(query, params).fetchall()
        return conn.execute(query).fetchall()
