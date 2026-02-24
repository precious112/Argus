"""REST API endpoints for Argus agent server."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """List alerts with pagination, optionally filtering by resolved status, severity, and state."""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    # Try DB first
    try:
        from argus_agent.storage.alert_history import AlertHistoryService

        svc = AlertHistoryService()
        items, total = await svc.list_alerts(
            resolved=resolved, severity=severity, status=status,
            limit=page_size, offset=offset,
        )
        if items or total > 0:
            total_pages = max(1, (total + page_size - 1) // page_size)
            return {
                "alerts": items,
                "count": len(items),
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }
    except Exception:
        pass

    # Fall back to in-memory alerts
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        return {
            "alerts": [], "count": 0, "total": 0,
            "page": 1, "page_size": page_size, "total_pages": 1,
        }

    include_resolved = resolved is None or resolved
    alerts = engine.get_active_alerts(include_resolved=include_resolved)

    all_items = []
    for a in alerts:
        if severity and str(a.severity) != severity:
            continue
        a_status = "resolved" if a.resolved else ("acknowledged" if a.acknowledged_at else "active")
        if status and a_status != status:
            continue
        all_items.append({
            "id": a.id,
            "rule_id": a.rule_id,
            "rule_name": a.rule_name,
            "severity": str(a.severity),
            "message": a.event.message,
            "source": str(a.event.source),
            "event_type": str(a.event.event_type),
            "timestamp": a.timestamp.isoformat(),
            "resolved": a.resolved,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            "status": a_status,
            "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
            "acknowledged_by": a.acknowledged_by,
        })

    total = len(all_items)
    items = all_items[offset : offset + page_size]
    total_pages = max(1, (total + page_size - 1) // page_size)

    return {
        "alerts": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


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

    # Persist to DB
    try:
        from argus_agent.storage.alert_history import AlertHistoryService

        await AlertHistoryService().update_status(
            alert_id,
            status="resolved",
            resolved=True,
            resolved_at=datetime.now(UTC),
        )
    except Exception:
        pass  # Don't break the endpoint if DB write fails

    return {"status": "resolved", "alert_id": alert_id}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Acknowledge an alert and suppress its dedup_key."""
    from argus_agent.alerting.suppression import SuppressionService
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Alert engine not initialized")

    body = body or {}
    expires_hours = float(body.get("expires_hours", 24))
    reason = body.get("reason", "")

    expires_at = datetime.now(UTC) + timedelta(hours=expires_hours)

    success = engine.acknowledge_alert(alert_id, acknowledged_by="user", expires_at=expires_at)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Persist suppression to DB
    alert = next((a for a in engine._active_alerts if a.id == alert_id), None)
    if alert:
        dedup_key = alert.dedup_key or f"{alert.event.source}:{alert.rule_id}"
        svc = SuppressionService()
        await svc.acknowledge(
            dedup_key=dedup_key,
            rule_id=alert.rule_id,
            source=str(alert.event.source),
            acknowledged_by="user",
            reason=reason,
            expires_at=expires_at,
        )

    # Persist alert status to DB
    try:
        from argus_agent.storage.alert_history import AlertHistoryService

        await AlertHistoryService().update_status(
            alert_id,
            status="acknowledged",
            acknowledged_at=datetime.now(UTC),
            acknowledged_by="user",
        )
    except Exception:
        pass

    return {"status": "acknowledged", "alert_id": alert_id}


@router.post("/alerts/{alert_id}/unacknowledge")
async def unacknowledge_alert(alert_id: str) -> dict[str, Any]:
    """Remove acknowledgment from an alert."""
    from argus_agent.alerting.suppression import SuppressionService
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Alert engine not initialized")

    # Get dedup_key before removing from engine
    alert = next((a for a in engine._active_alerts if a.id == alert_id), None)

    success = engine.unacknowledge_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found or not acknowledged")

    # Remove suppression from DB
    if alert:
        dedup_key = alert.dedup_key or f"{alert.event.source}:{alert.rule_id}"
        svc = SuppressionService()
        await svc.unacknowledge(dedup_key)

    # Persist alert status to DB
    try:
        from argus_agent.storage.alert_history import AlertHistoryService

        await AlertHistoryService().update_status(
            alert_id,
            status="active",
            acknowledged_at=None,
            acknowledged_by="",
        )
    except Exception:
        pass

    return {"status": "active", "alert_id": alert_id}


@router.post("/rules/{rule_id}/mute")
async def mute_rule(rule_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mute a rule for N hours (default 24, max 168)."""
    from argus_agent.alerting.suppression import SuppressionService
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Alert engine not initialized")

    body = body or {}
    duration_hours = min(float(body.get("duration_hours", 24)), 168)
    reason = body.get("reason", "")

    expires_at = datetime.now(UTC) + timedelta(hours=duration_hours)

    success = engine.mute_rule(rule_id, expires_at)
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Persist to DB
    svc = SuppressionService()
    await svc.mute_rule(
        rule_id=rule_id,
        muted_by="user",
        reason=reason,
        expires_at=expires_at,
    )

    return {"status": "muted", "rule_id": rule_id, "expires_at": expires_at.isoformat()}


@router.post("/rules/{rule_id}/unmute")
async def unmute_rule(rule_id: str) -> dict[str, Any]:
    """Unmute a rule."""
    from argus_agent.alerting.suppression import SuppressionService
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Alert engine not initialized")

    engine.unmute_rule(rule_id)

    svc = SuppressionService()
    await svc.unmute_rule(rule_id)

    return {"status": "unmuted", "rule_id": rule_id}


@router.get("/rules")
async def list_rules() -> dict[str, Any]:
    """List all alert rules with mute status."""
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        return {"rules": [], "count": 0}

    rules = engine.get_rules()
    muted = engine.get_muted_rules()

    items = []
    for rule in rules.values():
        mute_expires = muted.get(rule.id)
        items.append({
            "id": rule.id,
            "name": rule.name,
            "event_types": rule.event_types,
            "min_severity": str(rule.min_severity),
            "max_severity": str(rule.max_severity) if rule.max_severity else None,
            "cooldown_seconds": rule.cooldown_seconds,
            "auto_investigate": rule.auto_investigate,
            "muted": rule.id in muted,
            "mute_expires_at": mute_expires.isoformat() if mute_expires else None,
        })

    return {"rules": items, "count": len(items)}


@router.get("/alerts/suppression")
async def get_suppression_status() -> dict[str, Any]:
    """Return current acknowledged keys and muted rules."""
    from argus_agent.main import _get_alert_engine

    engine = _get_alert_engine()
    if engine is None:
        return {"acknowledged_keys": {}, "muted_rules": {}}

    ack_keys = engine.get_acknowledged_keys()
    muted = engine.get_muted_rules()

    return {
        "acknowledged_keys": {
            k: v.isoformat() for k, v in ack_keys.items()
        },
        "muted_rules": {
            k: v.isoformat() for k, v in muted.items()
        },
    }


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
            source="user_chat",
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
    from argus_agent.llm.settings import LLMSettingsService
    from argus_agent.main import _get_token_budget

    settings = get_settings()
    budget = _get_token_budget()

    # Discover available LLM providers
    from argus_agent.llm.registry import _discover_providers, _providers

    _discover_providers()
    available_providers = list(_providers.keys())

    # Check if settings are DB-persisted
    llm_svc = LLMSettingsService()
    db_persisted = await llm_svc.has_persisted_settings()

    return {
        "llm": {
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "status": _get_llm_status(),
            "api_key_set": bool(settings.llm.api_key),
            "providers": available_providers,
            "source": "db" if db_persisted else "env/yaml",
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
        "notifications": await _get_notification_configs(),
        "server": {
            "host": settings.server.host,
            "port": settings.server.port,
        },
    }


def _persist_to_yaml(section: str, data: dict[str, Any]) -> None:
    """Merge *data* into the *section* of argus.yaml and write it back."""
    from pathlib import Path

    import yaml

    candidates = [Path("argus.yaml"), Path("argus.yml")]
    config_path = None
    for c in candidates:
        if c.exists():
            config_path = c
            break
    if config_path is None:
        config_path = Path("argus.yaml")

    existing: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            existing = yaml.safe_load(f) or {}

    if section not in existing:
        existing[section] = {}
    existing[section].update(data)

    with open(config_path, "w") as f:
        yaml.safe_dump(existing, f, default_flow_style=False)


@router.put("/settings/llm")
async def update_llm_settings(body: dict[str, Any]) -> dict[str, Any]:
    """Update LLM provider, model, and/or API key (persisted to DB)."""
    from argus_agent.config import get_settings
    from argus_agent.llm.settings import LLMSettingsService

    settings = get_settings()

    provider = body.get("provider")
    model = body.get("model")
    api_key = body.get("api_key", "")

    # Update in-memory settings for immediate effect
    if provider:
        settings.llm.provider = provider
    if model:
        settings.llm.model = model
    if api_key and api_key != "••••••••":
        settings.llm.api_key = api_key

    # Persist to DB (replaces YAML persistence for LLM settings)
    persist_data: dict[str, Any] = {}
    if provider:
        persist_data["provider"] = provider
    if model:
        persist_data["model"] = model
    if api_key and api_key != "••••••••":
        persist_data["api_key"] = api_key

    llm_svc = LLMSettingsService()
    await llm_svc.save(persist_data)

    return {
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "api_key_set": bool(settings.llm.api_key),
        "status": _get_llm_status(),
    }


@router.put("/settings/budget")
async def update_budget_settings(body: dict[str, Any]) -> dict[str, Any]:
    """Update AI budget limits (daily/hourly token limits)."""
    from argus_agent.config import get_settings
    from argus_agent.main import _get_token_budget

    settings = get_settings()
    budget = _get_token_budget()

    daily = body.get("daily_token_limit")
    hourly = body.get("hourly_token_limit")

    if daily is not None:
        daily = int(daily)
        settings.ai_budget.daily_token_limit = daily
        if budget:
            budget._daily_limit = daily

    if hourly is not None:
        hourly = int(hourly)
        settings.ai_budget.hourly_token_limit = hourly
        if budget:
            budget._hourly_limit = hourly

    # Persist
    persist_data: dict[str, Any] = {
        "daily_token_limit": settings.ai_budget.daily_token_limit,
        "hourly_token_limit": settings.ai_budget.hourly_token_limit,
    }
    _persist_to_yaml("ai_budget", persist_data)

    return budget.get_status() if budget else {}


# --- Notification Settings Endpoints ---


@router.get("/notifications/settings")
async def get_notification_settings() -> dict[str, Any]:
    """Return all notification channel configs (secrets masked)."""
    from argus_agent.alerting.settings import NotificationSettingsService

    svc = NotificationSettingsService()
    configs = await svc.get_all()
    return {"channels": configs}


@router.put("/notifications/settings/{channel_type}")
async def upsert_notification_setting(
    channel_type: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Create or update a notification channel config, then reload channels."""
    if channel_type not in ("slack", "email", "webhook"):
        raise HTTPException(status_code=400, detail="Invalid channel_type")

    from argus_agent.alerting.reload import reload_channels
    from argus_agent.alerting.settings import NotificationSettingsService

    svc = NotificationSettingsService()
    result = await svc.upsert(
        channel_type=channel_type,
        enabled=body.get("enabled", False),
        config=body.get("config", {}),
    )
    await reload_channels()
    return result


@router.post("/notifications/test/{channel_type}")
async def test_notification(channel_type: str) -> dict[str, Any]:
    """Send a test notification for the given channel type."""
    if channel_type not in ("slack", "email", "webhook"):
        raise HTTPException(status_code=400, detail="Invalid channel_type")

    from argus_agent.alerting.settings import NotificationSettingsService

    svc = NotificationSettingsService()
    raw = await svc.get_by_type_raw(channel_type)
    if raw is None:
        raise HTTPException(status_code=404, detail="Channel not configured")

    cfg = raw["config"]

    try:
        if channel_type == "slack":
            from argus_agent.alerting.channels import SlackChannel

            ch = SlackChannel(
                bot_token=cfg.get("bot_token", ""),
                channel_id=cfg.get("channel_id", ""),
            )
            return await ch.test_connection()

        if channel_type == "email":
            from argus_agent.alerting.channels import EmailChannel

            ch = EmailChannel(
                smtp_host=cfg.get("smtp_host", ""),
                smtp_port=cfg.get("smtp_port", 587),
                from_addr=cfg.get("from_addr", ""),
                to_addrs=cfg.get("to_addrs", []),
                smtp_user=cfg.get("smtp_user", ""),
                smtp_password=cfg.get("smtp_password", ""),
                use_tls=cfg.get("use_tls", True),
            )
            return await ch.test_connection()

        # webhook — no dedicated test, just confirm config exists
        return {"ok": True, "urls": len(cfg.get("urls", []))}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/notifications/slack/channels")
async def list_slack_channels() -> dict[str, Any]:
    """List Slack channels using the stored bot token."""
    from argus_agent.alerting.settings import NotificationSettingsService

    svc = NotificationSettingsService()
    raw = await svc.get_by_type_raw("slack")
    if raw is None:
        raise HTTPException(status_code=404, detail="Slack not configured")

    try:
        from argus_agent.alerting.channels import SlackChannel

        ch = SlackChannel(
            bot_token=raw["config"].get("bot_token", ""),
            channel_id="",
        )
        channels = await ch.list_channels()
        return {"channels": channels}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --- Analytics Endpoints ---


@router.get("/analytics/usage")
async def analytics_usage(
    granularity: str = "hour",
    since_hours: int = 24,
    provider: str | None = None,
    model: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Time-series token usage data."""
    from argus_agent.storage.token_usage import TokenUsageService

    if granularity not in ("hour", "day", "week", "month"):
        raise HTTPException(status_code=400, detail="Invalid granularity")

    since = datetime.now(UTC) - timedelta(hours=since_hours)
    svc = TokenUsageService()
    data = await svc.get_usage_over_time(
        granularity=granularity, since=since,
        provider=provider, model=model, source=source,
    )
    return {"granularity": granularity, "data": data}


@router.get("/analytics/breakdown")
async def analytics_breakdown(
    group_by: str = "provider",
    since_hours: int = 24,
) -> dict[str, Any]:
    """Categorical breakdown of token usage."""
    from argus_agent.storage.token_usage import TokenUsageService

    if group_by not in ("provider", "model", "source"):
        raise HTTPException(status_code=400, detail="Invalid group_by")

    since = datetime.now(UTC) - timedelta(hours=since_hours)
    svc = TokenUsageService()
    data = await svc.get_usage_by_dimension(dimension=group_by, since=since)
    return {"group_by": group_by, "data": data}


@router.get("/analytics/summary")
async def analytics_summary() -> dict[str, Any]:
    """Aggregate token usage stats."""
    from argus_agent.storage.token_usage import TokenUsageService

    svc = TokenUsageService()
    return await svc.get_summary()


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


async def _get_notification_configs() -> list[dict[str, Any]]:
    """Get notification channel configs for the settings endpoint."""
    try:
        from argus_agent.alerting.settings import NotificationSettingsService

        svc = NotificationSettingsService()
        return await svc.get_all()
    except Exception:
        return []


def _get_llm_status() -> str:
    """Get LLM provider status."""
    try:
        from argus_agent.llm.registry import get_provider

        provider = get_provider()
        return provider.name
    except Exception:
        return "not_configured"
