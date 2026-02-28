"""Repository protocol interfaces for storage abstraction.

These protocols allow swapping database backends (DuckDB → TimescaleDB,
SQLite → PostgreSQL) without changing business logic in tools, API routes,
and the agent layer.

In self-hosted mode the implementations delegate to the existing DuckDB
and SQLite functions.  In SaaS mode, PostgreSQL/TimescaleDB implementations
will fulfill the same interfaces.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Metrics Repository — time-series data (DuckDB / TimescaleDB)
# ---------------------------------------------------------------------------


@runtime_checkable
class MetricsRepository(Protocol):
    """Protocol for time-series metrics storage.

    Covers system metrics, log index, SDK events, spans, dependencies,
    deploy events, SDK metrics, and baselines.
    """

    # --- Lifecycle ---

    def init(self, db_path: str) -> None: ...
    def close(self) -> None: ...

    # --- System Metrics ---

    def insert_metric(
        self,
        metric_name: str,
        value: float,
        labels: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> None: ...

    def insert_metrics_batch(
        self,
        rows: list[tuple[datetime, str, float, dict[str, str] | None]],
    ) -> None: ...

    def query_metrics(
        self,
        metric_name: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]: ...

    def query_metrics_summary(
        self,
        metric_name: str,
        since: datetime | None = None,
    ) -> dict[str, Any]: ...

    def query_latest_metrics(self) -> dict[str, float]: ...

    # --- Log Index ---

    def insert_log_entry(
        self,
        file_path: str,
        line_offset: int,
        severity: str = "",
        message_preview: str = "",
        source: str = "",
        timestamp: datetime | None = None,
    ) -> None: ...

    def query_log_entries(
        self,
        severity: str | None = None,
        file_path: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    # --- SDK Events ---

    def insert_sdk_event(
        self,
        timestamp: datetime,
        service: str,
        event_type: str,
        data: str,
    ) -> None: ...

    def query_service_summary(
        self,
        service: str = "",
        since_minutes: int = 1440,
    ) -> list[dict[str, Any]]: ...

    def query_error_groups(
        self,
        service: str = "",
        since_minutes: int = 1440,
        limit: int = 20,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def query_function_metrics(
        self,
        service: str = "",
        function_name: str = "",
        since_minutes: int = 60,
        interval_minutes: int = 5,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

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
    ) -> None: ...

    def query_trace(
        self,
        trace_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    def query_slow_spans(
        self,
        service: str = "",
        since_minutes: int = 60,
        limit: int = 20,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def query_trace_summary(
        self,
        service: str = "",
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def query_request_metrics(
        self,
        service: str = "",
        path: str = "",
        method: str = "",
        since_minutes: int = 60,
        interval_minutes: int = 5,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    # --- SDK Metrics ---

    def insert_sdk_metric(
        self,
        service: str,
        metric_name: str,
        value: float,
        labels: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> None: ...

    def query_sdk_metrics(
        self,
        service: str = "",
        metric_name: str = "",
        since_minutes: int = 60,
        limit: int = 500,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

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
    ) -> None: ...

    def query_dependencies(
        self,
        service: str = "",
        dep_type: str = "",
        since_minutes: int = 60,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    def query_dependency_summary(
        self,
        service: str = "",
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def query_dependency_map(
        self,
        since_minutes: int = 60,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

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
    ) -> None: ...

    def query_deploy_history(
        self,
        service: str = "",
        since_minutes: int = 10080,
        limit: int = 50,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_previous_deploy_version(
        self,
        service: str,
    ) -> str | None: ...

    # --- Error Fingerprinting ---

    def compute_error_fingerprint(
        self,
        error_type: str,
        traceback_str: str,
    ) -> str: ...

    # --- Raw Query Access ---

    def execute_raw(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[tuple[Any, ...]]: ...


# ---------------------------------------------------------------------------
# Operational Repository — transactional data (SQLite / PostgreSQL)
# ---------------------------------------------------------------------------


@runtime_checkable
class OperationalRepository(Protocol):
    """Protocol for operational/transactional storage.

    Provides async session management for SQLAlchemy ORM access.
    """

    async def init(self, db_path: str) -> None: ...
    async def close(self) -> None: ...
    def get_session(self) -> AsyncSession: ...


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

_metrics_repo: MetricsRepository | None = None
_operational_repo: OperationalRepository | None = None


def set_metrics_repository(repo: MetricsRepository) -> None:
    """Set the global metrics repository instance."""
    global _metrics_repo
    _metrics_repo = repo


def get_metrics_repository() -> MetricsRepository:
    """Get the global metrics repository instance."""
    if _metrics_repo is None:
        raise RuntimeError("Metrics repository not initialized.")
    return _metrics_repo


def set_operational_repository(repo: OperationalRepository) -> None:
    """Set the global operational repository instance."""
    global _operational_repo
    _operational_repo = repo


def get_operational_repository() -> OperationalRepository:
    """Get the global operational repository instance."""
    if _operational_repo is None:
        raise RuntimeError("Operational repository not initialized.")
    return _operational_repo
