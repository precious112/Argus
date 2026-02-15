"""REST API endpoints for Argus agent server."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from argus_agent import __version__

router = APIRouter(tags=["api"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/status")
async def system_status() -> dict[str, Any]:
    """Get current system status summary."""
    from argus_agent.collectors.system_metrics import get_system_snapshot
    from argus_agent.config import get_settings
    from argus_agent.main import _get_collectors

    settings = get_settings()
    is_sdk_only = settings.mode == "sdk_only"

    metrics_col, process_mon, log_watch, scheduler = _get_collectors()

    collector_status: dict[str, str] = {}
    if not is_sdk_only:
        collector_status = {
            "system_metrics": "running" if metrics_col and metrics_col.is_running else "stopped",
            "process_monitor": "running" if process_mon and process_mon.is_running else "stopped",
            "log_watcher": "running" if log_watch and log_watch.is_running else "stopped",
        }

    snapshot = get_system_snapshot() if not is_sdk_only else {}

    result: dict[str, Any] = {
        "status": "ok",
        "version": __version__,
        "mode": settings.mode,
        "collectors": collector_status,
        "system": snapshot if snapshot else {},
        "agent": {
            "active_conversations": 0,
            "llm_provider": _get_llm_status(),
        },
    }

    if scheduler and scheduler.is_running:
        result["scheduler"] = scheduler.get_status()

    if log_watch and not is_sdk_only:
        result["watched_files"] = log_watch.watched_files

    return result


# --- Phase 3 Endpoints ---


@router.get("/alerts")
async def list_alerts(
    resolved: bool | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    """List alerts, optionally filtering by resolved status and severity."""
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        return {"alerts": [], "count": 0}

    include_resolved = resolved is True if resolved is not None else False
    alerts = engine.get_active_alerts(include_resolved=include_resolved or resolved is None)

    items = []
    for a in alerts:
        if resolved is not None and a.resolved != resolved:
            continue
        if severity and str(a.severity) != severity.upper():
            continue
        items.append({
            "id": a.id,
            "rule_id": a.rule_id,
            "rule_name": a.rule_name,
            "severity": str(a.severity),
            "message": a.event.message,
            "source": str(a.event.source),
            "event_type": str(a.event.type),
            "timestamp": a.timestamp.isoformat(),
            "resolved": a.resolved,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        })

    return {"alerts": items, "count": len(items)}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str) -> dict[str, Any]:
    """Mark an alert as resolved."""
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Alert engine not initialized")

    success = engine.resolve_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")

    return {"status": "resolved", "alert_id": alert_id}


@router.get("/budget")
async def token_budget_status() -> dict[str, Any]:
    """Get current AI token budget status."""
    from argus_agent.main import _get_token_budget

    budget = _get_token_budget()
    if budget is None:
        return {"error": "Budget not initialized"}

    return budget.get_status()


@router.get("/investigations")
async def list_investigations() -> dict[str, Any]:
    """List recent AI investigations."""
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        return {"investigations": []}

    # For now, return alerts that triggered auto-investigation
    alerts = engine.get_active_alerts(include_resolved=True)
    investigations = []
    for a in alerts:
        if a.event.severity.value == "URGENT":
            investigations.append({
                "alert_id": a.id,
                "trigger": a.event.message,
                "severity": str(a.severity),
                "timestamp": a.timestamp.isoformat(),
                "resolved": a.resolved,
            })

    return {"investigations": investigations}


@router.get("/security")
async def security_scan_results() -> dict[str, Any]:
    """Get the latest security scan results."""
    from argus_agent.main import _get_security_scanner

    scanner = _get_security_scanner()
    if scanner is None:
        return {"error": "Security scanner not initialized", "checks": {}}

    return scanner.last_results or {"checks": {}, "message": "No scan results yet"}


@router.get("/logs")
async def get_logs(
    limit: int = 50,
    severity: str | None = None,
) -> dict[str, Any]:
    """Get recent log entries from DuckDB."""
    try:
        from argus_agent.storage.timeseries import query_log_entries

        entries = query_log_entries(severity=severity, limit=min(limit, 200))
        return {"entries": entries, "count": len(entries)}
    except RuntimeError:
        return {"entries": [], "count": 0, "error": "Storage not initialized"}


@router.post("/ask")
async def ask_question(
    body: dict[str, Any],
    client: str = "web",
) -> dict[str, Any]:
    """One-off question to the agent (non-streaming)."""
    question = body.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="No question provided")

    client_type = client if client in ("cli", "web") else "web"

    try:
        from argus_agent.agent.loop import AgentLoop
        from argus_agent.agent.memory import ConversationMemory
        from argus_agent.api.ws import _get_provider

        provider = _get_provider()
        if provider is None:
            return {"answer": "LLM provider not configured.", "error": "no_provider"}

        memory = ConversationMemory()
        agent = AgentLoop(
            provider=provider, memory=memory,
            client_type=client_type,
        )
        result = await agent.run(question)
        return {
            "answer": result.content,
            "tokens": {
                "prompt": result.prompt_tokens,
                "completion": result.completion_tokens,
            },
        }
    except Exception as e:
        return {"answer": "", "error": str(e)}


@router.get("/services")
async def list_services() -> dict[str, Any]:
    """List all services sending SDK telemetry with health summary."""
    try:
        from argus_agent.storage.timeseries import query_service_summary

        summaries = query_service_summary(since_minutes=1440)
        return {"services": summaries, "count": len(summaries)}
    except RuntimeError:
        return {"services": [], "count": 0, "error": "Storage not initialized"}


@router.get("/services/{service}/metrics")
async def service_metrics(
    service: str,
    since_minutes: int = 60,
    interval_minutes: int = 5,
) -> dict[str, Any]:
    """Get aggregated metrics for a specific service."""
    try:
        from argus_agent.storage.timeseries import (
            query_error_groups,
            query_function_metrics,
        )

        buckets = query_function_metrics(
            service=service,
            since_minutes=since_minutes,
            interval_minutes=interval_minutes,
        )
        errors = query_error_groups(service=service, since_minutes=since_minutes)

        return {
            "service": service,
            "metrics": buckets,
            "error_groups": errors,
            "since_minutes": since_minutes,
        }
    except RuntimeError:
        return {
            "service": service,
            "metrics": [],
            "error_groups": [],
            "error": "Storage not initialized",
        }


@router.get("/settings")
async def get_settings_endpoint() -> dict[str, Any]:
    """Get sanitized server settings (no secrets)."""
    from argus_agent.config import get_settings
    from argus_agent.main import _get_token_budget

    settings = get_settings()
    budget = _get_token_budget()

    return {
        "llm": {
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "status": _get_llm_status(),
        },
        "budget": budget.get_status() if budget else {},
        "collectors": {
            "metrics_interval": settings.collector.metrics_interval,
            "process_interval": settings.collector.process_interval,
            "log_paths": settings.collector.log_paths,
        },
        "alerting": {
            "webhook_count": len(settings.alerting.webhook_urls),
            "email_enabled": settings.alerting.email_enabled,
        },
        "server": {
            "host": settings.server.host,
            "port": settings.server.port,
        },
    }


@router.get("/audit")
async def audit_log(
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Get paginated action audit log."""
    from argus_agent.actions.audit import AuditLogger

    logger = AuditLogger()
    entries = await logger.get_audit_log(limit=min(limit, 200), offset=offset)
    return {"entries": entries, "count": len(entries), "offset": offset}


def _get_llm_status() -> str:
    """Get LLM provider status."""
    try:
        from argus_agent.llm.registry import get_provider

        provider = get_provider()
        return provider.name
    except Exception:
        return "not_configured"
