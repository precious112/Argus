"""FastAPI entry point for Argus agent server."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import JSONResponse

from argus_agent.api.auth import router as auth_router
from argus_agent.api.ingest import router as ingest_router
from argus_agent.api.rest import router as rest_router
from argus_agent.api.ws import router as ws_router
from argus_agent.auth.jwt import decode_access_token
from argus_agent.config import ensure_secret_key, get_settings
from argus_agent.storage.duckdb_metrics import DuckDBMetricsRepository
from argus_agent.storage.repositories import (
    set_metrics_repository,
    set_operational_repository,
)
from argus_agent.storage.sqlite_operational import SQLiteOperationalRepository

logger = logging.getLogger("argus")

# Global references to background services for status queries
_metrics_collector = None
_process_monitor = None
_log_watcher = None
_scheduler = None
_security_scanner = None
_alert_engine = None
_token_budget = None
_baseline_tracker = None
_anomaly_detector = None
_investigator = None
_action_engine = None
_sdk_telemetry_collector = None
_soak_runner = None
_alert_formatter = None


def _get_collectors():
    """Get collector instances (for status endpoint)."""
    return _metrics_collector, _process_monitor, _log_watcher, _scheduler


def _get_security_scanner():
    """Get the security scanner instance."""
    return _security_scanner


def _get_alert_engine():
    """Get the alert engine instance."""
    return _alert_engine


def _get_token_budget():
    """Get the token budget instance."""
    return _token_budget


def _get_baseline_tracker():
    """Get the baseline tracker instance."""
    return _baseline_tracker


def _get_investigator():
    """Get the investigator instance."""
    return _investigator


def _get_action_engine():
    """Get the action engine instance."""
    return _action_engine


def _get_alert_formatter():
    """Get the alert formatter instance."""
    return _alert_formatter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    global _metrics_collector, _process_monitor, _log_watcher, _scheduler
    global _security_scanner, _alert_engine, _token_budget
    global _baseline_tracker, _anomaly_detector, _investigator, _action_engine
    global _sdk_telemetry_collector, _soak_runner, _alert_formatter

    settings = get_settings()

    # Ensure data directory exists
    Path(settings.storage.data_dir).mkdir(parents=True, exist_ok=True)

    # Auto-generate JWT secret key if still using the default
    ensure_secret_key(settings)

    # Initialize license manager
    from argus_agent.licensing import init_license_manager

    lm = init_license_manager(settings.license.key)
    logger.info(
        "Argus edition: %s (%d features enabled)",
        lm.edition.value,
        len(lm.get_enabled_features()),
    )

    # Initialize databases via repository pattern
    if settings.deployment.mode == "saas":
        # PostgreSQL + TimescaleDB + Redis
        from argus_agent.auth.key_cache import init_key_cache
        from argus_agent.storage.postgres_operational import PostgresOperationalRepository
        from argus_agent.storage.timescaledb_metrics import TimescaleDBMetricsRepository

        operational_repo = PostgresOperationalRepository()
        await operational_repo.init(settings.deployment.postgres_url)
        set_operational_repository(operational_repo)

        metrics_repo = TimescaleDBMetricsRepository()
        metrics_repo.init(settings.deployment.timescale_url)
        set_metrics_repository(metrics_repo)

        await init_key_cache(settings.deployment.redis_url)
        logger.info("SaaS mode: PostgreSQL + TimescaleDB + Redis initialized")
    else:
        # Self-hosted: SQLite + DuckDB (unchanged)
        operational_repo = SQLiteOperationalRepository()
        await operational_repo.init(settings.storage.sqlite_path)
        set_operational_repository(operational_repo)

        metrics_repo = DuckDBMetricsRepository()
        metrics_repo.init(settings.storage.duckdb_path)
        set_metrics_repository(metrics_repo)

    # Apply DB-persisted LLM settings (overrides env/YAML defaults)
    from argus_agent.llm.settings import LLMSettingsService

    await LLMSettingsService().apply_to_settings()

    # Register all tools (skip host tools in SDK-only mode)
    _register_all_tools(is_sdk_only=settings.mode == "sdk_only")

    # --- Phase 3: Proactive Intelligence ---

    # 1. Token budget
    from argus_agent.scheduler.budget import TokenBudget

    _token_budget = TokenBudget(settings.ai_budget)

    # 2. Baseline tracker + anomaly detector
    from argus_agent.baseline.anomaly import AnomalyDetector
    from argus_agent.baseline.tracker import BaselineTracker

    _baseline_tracker = BaselineTracker()
    _anomaly_detector = AnomalyDetector(_baseline_tracker)

    # 3. Investigator + Alert formatter
    from argus_agent.agent.investigator import Investigator
    from argus_agent.alerting.formatter import AlertFormatter
    from argus_agent.api.ws import manager

    _alert_formatter = AlertFormatter(
        channels=[],
        batch_window=settings.alerting.batch_window,
        min_severity=settings.alerting.min_external_severity,
        ai_enhance=settings.alerting.ai_enhance,
    )

    _investigator = Investigator(
        budget=_token_budget,
        ws_manager=manager,
        formatter=_alert_formatter,
    )
    await _investigator.start()

    # 3b. Action engine
    from argus_agent.actions.engine import ActionEngine

    _action_engine = ActionEngine(ws_manager=manager)

    # 4. Alert engine with channels (DB-backed)
    from argus_agent.alerting.engine import AlertEngine
    from argus_agent.alerting.reload import reload_channels
    from argus_agent.alerting.settings import NotificationSettingsService
    from argus_agent.events.bus import get_event_bus

    _alert_engine = AlertEngine(
        bus=get_event_bus(),
        on_investigate=_investigator.enqueue_investigation,
    )
    # Seed DB from static config on first run
    svc = NotificationSettingsService()
    await svc.initialize_from_config(settings.alerting)
    _alert_engine.set_formatter(_alert_formatter)
    # Load channels from DB (sets WS on engine, external on formatter)
    await reload_channels()
    await _alert_formatter.start()
    await _alert_engine.start()

    # Load persisted acknowledgments and mutes into the alert engine
    from argus_agent.alerting.suppression import SuppressionService

    await SuppressionService().load_into_engine(_alert_engine)

    is_sdk_only = settings.mode == "sdk_only"

    # Start host-level collectors only in full mode
    if not is_sdk_only:
        from argus_agent.collectors.log_watcher import LogWatcher
        from argus_agent.collectors.process_monitor import ProcessMonitor
        from argus_agent.collectors.system_metrics import SystemMetricsCollector

        _metrics_collector = SystemMetricsCollector()
        _metrics_collector.anomaly_detector = _anomaly_detector
        _process_monitor = ProcessMonitor()
        _log_watcher = LogWatcher()

        await _metrics_collector.start()
        await _process_monitor.start()
        await _log_watcher.start()

        # Security scanner
        from argus_agent.collectors.security_scanner import SecurityScanner

        _security_scanner = SecurityScanner()
        await _security_scanner.start()

    # Start SDK telemetry virtual collector (both modes)
    from argus_agent.collectors.sdk_telemetry import SDKTelemetryCollector

    _sdk_telemetry_collector = SDKTelemetryCollector()
    _sdk_telemetry_collector.anomaly_detector = _anomaly_detector
    await _sdk_telemetry_collector.start()

    # Start scheduler with periodic tasks
    from argus_agent.scheduler.scheduler import Scheduler
    from argus_agent.scheduler.tasks import (
        quick_health_check,
        quick_security_check,
        trend_analysis,
    )

    _scheduler = Scheduler()

    if not is_sdk_only:
        _scheduler.register("health_check", quick_health_check, interval_seconds=300)
        _scheduler.register("trend_analysis", trend_analysis, interval_seconds=1800)
        _scheduler.register(
            "baseline_update",
            _make_baseline_update_task(_baseline_tracker),
            interval_seconds=21600,
        )
        _scheduler.register(
            "security_check",
            quick_security_check,
            interval_seconds=300,
        )

    # SDK baseline update (both modes)
    _scheduler.register(
        "sdk_baseline_update",
        _make_sdk_baseline_update_task(_baseline_tracker),
        interval_seconds=21600,  # 6h
    )

    _scheduler.register(
        "ai_periodic_review",
        _investigator.periodic_review,
        interval_seconds=21600,  # 6h
    )
    _scheduler.register(
        "ai_daily_digest",
        _investigator.daily_digest,
        interval_seconds=86400,  # 24h
    )
    await _scheduler.start()

    # Soak test runner (opt-in via ARGUS_SOAK_ENABLED=true)
    if os.environ.get("ARGUS_SOAK_ENABLED", "").lower() in ("true", "1", "yes"):
        from argus_agent.scheduler.soak import SoakTestRunner

        _soak_runner = SoakTestRunner()
        await _soak_runner.start()

    # Collect initial system snapshot for agent context (full mode only)
    if not is_sdk_only:
        from argus_agent.collectors.system_metrics import update_system_snapshot

        await update_system_snapshot()

    mode_str = "sdk_only" if is_sdk_only else "full"
    logger.info(
        "Argus agent server started on %s:%d (mode=%s)",
        settings.server.host, settings.server.port, mode_str,
    )
    yield

    # Shutdown in reverse order
    if _investigator:
        await _investigator.stop()
    if _alert_formatter:
        await _alert_formatter.stop()
    if _soak_runner:
        await _soak_runner.stop()
    if _scheduler:
        await _scheduler.stop()
    if _sdk_telemetry_collector:
        await _sdk_telemetry_collector.stop()
    if _security_scanner:
        await _security_scanner.stop()
    if _log_watcher:
        await _log_watcher.stop()
    if _process_monitor:
        await _process_monitor.stop()
    if _metrics_collector:
        await _metrics_collector.stop()

    # Clean up Redis in SaaS mode
    if settings.deployment.mode == "saas":
        from argus_agent.auth.key_cache import close_key_cache

        await close_key_cache()

    await operational_repo.close()
    metrics_repo.close()
    logger.info("Argus agent server stopped")


def _make_baseline_update_task(tracker):
    """Create a baseline update coroutine for the scheduler."""
    async def _update():
        tracker.update_baselines()
    return _update


def _make_sdk_baseline_update_task(tracker):
    """Create an SDK baseline update coroutine for the scheduler."""
    async def _update():
        tracker.update_sdk_baselines()
    return _update


def _register_all_tools(*, is_sdk_only: bool = False) -> None:
    """Register all agent tools.

    When *is_sdk_only* is True, host-level tools (metrics, process, network,
    security, command, log search) are skipped — they report data from the
    agent's own server which is irrelevant in SDK mode.
    """
    from argus_agent.tools.base import get_all_tools
    from argus_agent.tools.behavior import register_behavior_tools
    from argus_agent.tools.chart import register_chart_tools
    from argus_agent.tools.dependencies import register_dependency_tools
    from argus_agent.tools.deploys import register_deploy_tools
    from argus_agent.tools.error_analysis import register_error_analysis_tools
    from argus_agent.tools.function_metrics import register_function_metrics_tools
    from argus_agent.tools.runtime_metrics import register_runtime_metrics_tools
    from argus_agent.tools.sdk_events import register_sdk_tools
    from argus_agent.tools.traces import register_trace_tools

    if not get_all_tools():
        # Host-level tools — only in full mode
        if not is_sdk_only:
            from argus_agent.tools.command import register_command_tools
            from argus_agent.tools.log_search import register_log_tools
            from argus_agent.tools.metrics import register_metrics_tools
            from argus_agent.tools.network import register_network_tools
            from argus_agent.tools.process import register_process_tools
            from argus_agent.tools.security import register_security_tools

            register_log_tools()
            register_metrics_tools()
            register_process_tools()
            register_network_tools()
            register_security_tools()
            register_command_tools()

        # SDK / analysis tools — always registered
        register_sdk_tools()
        register_chart_tools()
        register_function_metrics_tools()
        register_error_analysis_tools()
        register_trace_tools()
        register_runtime_metrics_tools()
        register_dependency_tools()
        register_deploy_tools()
        register_behavior_tools()

        # Alert management tools — always registered
        from argus_agent.tools.alert_management import register_alert_management_tools

        register_alert_management_tools()

        # Pro tools — only when licensed
        try:
            from argus_agent.licensing import has_feature
            from argus_agent.licensing.editions import Feature

            if has_feature(Feature.ADVANCED_INTEGRATIONS):
                from argus_agent.pro.tools import register_pro_tools

                register_pro_tools()
        except ImportError:
            pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    get_settings()

    app = FastAPI(
        title="Argus Agent",
        description="AI-Native Observability Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for web UI
    cors_env = os.environ.get("ARGUS_CORS_ORIGINS", "")
    origins = [o.strip() for o in cors_env.split(",") if o.strip()] if cors_env else []
    origins += ["http://localhost:3000", "http://127.0.0.1:3000"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth middleware — protect /api/ routes (except exempt paths)
    auth_exempt = {
        "/health",
        "/api/v1/health",
        "/api/v1/license",
        "/api/v1/deployment-info",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/register",
        "/api/v1/auth/accept-invite",
        "/api/v1/billing/plans",
        "/api/v1/webhooks/polar",
    }
    auth_exempt_prefixes = (
        "/api/v1/ingest",
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if (
            path in auth_exempt
            or path.startswith(auth_exempt_prefixes)
            or not path.startswith("/api/")
        ):
            return await call_next(request)
        token = request.cookies.get("argus_token", "")
        if not token:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        try:
            payload = decode_access_token(token)
            request.state.user = payload
        except Exception:
            return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)
        return await call_next(request)

    # Tenant context middleware
    from argus_agent.tenancy.middleware import TenantMiddleware

    settings = get_settings()
    app.add_middleware(
        TenantMiddleware,
        is_saas=settings.deployment.mode == "saas",
    )

    # API routes
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(rest_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")
    app.include_router(ingest_router, prefix="/api/v1")

    # SaaS-only routers
    if settings.deployment.mode == "saas":
        from argus_agent.api.billing import router as billing_router
        from argus_agent.api.keys import router as keys_router
        from argus_agent.api.registration import router as reg_router
        from argus_agent.api.team import (
            accept_router,
        )
        from argus_agent.api.team import (
            router as team_router,
        )
        from argus_agent.api.webhooks import router as webhooks_router

        app.include_router(reg_router, prefix="/api/v1")
        app.include_router(team_router, prefix="/api/v1")
        app.include_router(keys_router, prefix="/api/v1")
        app.include_router(accept_router, prefix="/api/v1")
        app.include_router(billing_router, prefix="/api/v1")
        app.include_router(webhooks_router, prefix="/api/v1")

    # Serve static web UI in production
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()


def main() -> None:
    """Run the Argus agent server."""
    logging.basicConfig(
        level=logging.DEBUG if get_settings().debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = get_settings()
    uvicorn.run(
        "argus_agent.main:app",
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
