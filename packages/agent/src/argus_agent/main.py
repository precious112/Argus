"""FastAPI entry point for Argus agent server."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from argus_agent.api.ingest import router as ingest_router
from argus_agent.api.rest import router as rest_router
from argus_agent.api.ws import router as ws_router
from argus_agent.config import get_settings
from argus_agent.storage.database import close_db, init_db
from argus_agent.storage.timeseries import close_timeseries, init_timeseries

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    global _metrics_collector, _process_monitor, _log_watcher, _scheduler
    global _security_scanner, _alert_engine, _token_budget
    global _baseline_tracker, _anomaly_detector, _investigator, _action_engine
    global _sdk_telemetry_collector

    settings = get_settings()

    # Ensure data directory exists
    Path(settings.storage.data_dir).mkdir(parents=True, exist_ok=True)

    # Initialize databases
    await init_db(settings.storage.sqlite_path)
    init_timeseries(settings.storage.duckdb_path)

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

    # 3. Investigator
    from argus_agent.agent.investigator import Investigator
    from argus_agent.api.ws import manager

    _investigator = Investigator(
        budget=_token_budget,
        ws_manager=manager,
    )

    # 3b. Action engine
    from argus_agent.actions.engine import ActionEngine

    _action_engine = ActionEngine(ws_manager=manager)

    # 4. Alert engine with channels
    from argus_agent.alerting.channels import WebhookChannel, WebSocketChannel
    from argus_agent.alerting.engine import AlertEngine
    from argus_agent.events.bus import get_event_bus

    _alert_engine = AlertEngine(
        bus=get_event_bus(),
        on_investigate=_investigator.investigate_event,
    )
    channels = [WebSocketChannel(manager)]
    if settings.alerting.webhook_urls:
        channels.append(WebhookChannel(settings.alerting.webhook_urls))
    if settings.alerting.email_enabled:
        from argus_agent.alerting.channels import EmailChannel

        channels.append(EmailChannel(
            smtp_host=settings.alerting.email_smtp_host,
            smtp_port=settings.alerting.email_smtp_port,
            from_addr=settings.alerting.email_from,
            to_addrs=settings.alerting.email_to,
        ))
    _alert_engine.set_channels(channels)
    await _alert_engine.start()

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

    await close_db()
    close_timeseries()
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
    import os

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

    # API routes
    app.include_router(rest_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")
    app.include_router(ingest_router, prefix="/api/v1")

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
