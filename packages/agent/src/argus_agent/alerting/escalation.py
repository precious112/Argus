"""Escalation policy evaluation — routes alert emails to designated contacts."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from argus_agent.alerting.formatter import format_event
from argus_agent.events.types import Event, EventSeverity

logger = logging.getLogger("argus.alerting.escalation")

# Ordered severity levels for comparison
_SEVERITY_ORDER = ["NORMAL", "NOTABLE", "URGENT"]

# In-memory cache: tenant_id -> (policies_list, fetched_at)
_policy_cache: dict[str, tuple[list[dict[str, Any]], datetime]] = {}
_CACHE_TTL_SECONDS = 60


def _severity_index(severity: str) -> int:
    """Return numeric index for a severity string (unknown → -1)."""
    try:
        return _SEVERITY_ORDER.index(severity.upper())
    except ValueError:
        return -1


def _resolve_severity_str(severity: EventSeverity | str) -> str:
    """Return the string representation of a severity value."""
    if isinstance(severity, EventSeverity):
        return severity.value
    return str(severity)


def _extract_service_name(event: Event) -> str:
    """Extract service name from event data, falling back to event.source."""
    data = event.data or {}
    return data.get("service_name") or data.get("service") or event.source or ""


def _matches_policy(
    policy: dict[str, Any], event: Event, alert_severity: EventSeverity,
) -> bool:
    """Check if an escalation policy matches the given event and severity."""
    # Service filter (empty = match all)
    policy_service = policy.get("service_name", "")
    if policy_service:
        event_service = _extract_service_name(event)
        if event_service.lower() != policy_service.lower():
            return False

    # Severity filter (empty = match all)
    policy_min = policy.get("min_severity", "")
    if policy_min:
        policy_idx = _severity_index(policy_min)
        sev_str = _resolve_severity_str(alert_severity)
        alert_idx = _severity_index(sev_str)
        if alert_idx < policy_idx:
            return False

    return True


def _render_escalation_email(
    alert: Any,
    event: Event,
    policy_name: str,
    friendly_message: str,
) -> tuple[str, str]:
    """Render plain text and HTML email for an escalation notification.

    Returns (plain, html).
    """
    severity = _resolve_severity_str(alert.severity)
    source = str(event.source) if event.source else "unknown"
    ts = alert.timestamp.isoformat() if hasattr(alert, "timestamp") else ""

    plain = (
        f"[Argus Escalation] {alert.rule_name}\n"
        f"Policy: {policy_name}\n"
        f"Severity: {severity}\n"
        f"Source: {source}\n"
        f"Time: {ts}\n\n"
        f"{friendly_message}\n"
    )

    color_map = {
        "URGENT": "#e74c3c",
        "NOTABLE": "#f39c12",
        "NORMAL": "#2ecc71",
    }
    color = color_map.get(severity, "#95a5a6")

    html = (
        '<html><body style="margin:0;padding:0;'
        'font-family:Arial,Helvetica,sans-serif;background:#f4f4f7;">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="padding:24px;">'
        '<tr><td align="center">'
        '<table width="600" cellpadding="0" cellspacing="0" '
        'style="background:#ffffff;border-radius:8px;overflow:hidden;">'
        f'<tr><td style="background:{color};padding:16px 24px;">'
        f'<h2 style="margin:0;color:#fff;font-size:18px;">'
        f"Argus Escalation: {alert.rule_name}</h2>"
        f'<p style="margin:4px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">'
        f"Policy: {policy_name}</p>"
        "</td></tr>"
        '<tr><td style="padding:24px;">'
        f'<p style="margin:0 0 8px;font-size:13px;color:#666;">Severity: {severity}</p>'
        f'<p style="margin:0 0 8px;font-size:13px;color:#666;">Source: {source}</p>'
        f'<p style="margin:0 0 8px;font-size:13px;color:#666;">Time: {ts}</p>'
        f'<div style="margin-top:16px;padding:12px;background:#f8f9fa;'
        f'border-left:4px solid {color};font-size:14px;white-space:pre-wrap;">'
        f"{friendly_message}</div>"
        "</td></tr></table></td></tr></table></body></html>"
    )
    return plain, html


async def _get_active_policies(tenant_id: str) -> list[dict[str, Any]]:
    """Fetch active escalation policies for a tenant (cached 60s)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    cached = _policy_cache.get(tenant_id)
    if cached:
        policies, fetched_at = cached
        if (now - fetched_at).total_seconds() < _CACHE_TTL_SECONDS:
            return policies

    try:
        from sqlalchemy import select

        from argus_agent.storage.repositories import get_session
        from argus_agent.storage.saas_models import EscalationPolicy

        async with get_session() as session:
            result = await session.execute(
                select(EscalationPolicy).where(
                    EscalationPolicy.tenant_id == tenant_id,
                    EscalationPolicy.is_active.is_(True),
                )
            )
            rows = result.scalars().all()
            # Detach from session: store as plain dicts
            policies = [
                {
                    "id": r.id,
                    "name": r.name,
                    "service_name": r.service_name,
                    "min_severity": r.min_severity,
                    "primary_contact_id": r.primary_contact_id,
                    "backup_contact_id": r.backup_contact_id,
                }
                for r in rows
            ]
        _policy_cache[tenant_id] = (policies, now)
        return policies
    except Exception:
        logger.debug("Failed to fetch escalation policies for tenant %s", tenant_id, exc_info=True)
        return []


async def _resolve_user_email(user_id: str) -> str | None:
    """Look up a user's email by ID."""
    if not user_id:
        return None
    try:
        from sqlalchemy import select

        from argus_agent.storage.models import User
        from argus_agent.storage.repositories import get_session

        async with get_session() as session:
            result = await session.execute(
                select(User.email).where(User.id == user_id)
            )
            row = result.scalar_one_or_none()
            return row if row else None
    except Exception:
        logger.debug("Failed to resolve email for user %s", user_id, exc_info=True)
        return None


async def notify_escalation_contacts(alert: Any, event: Event) -> None:
    """Send escalation emails to contacts matching the alert.

    Skips silently in self-hosted mode or for the default tenant.
    """
    try:
        from argus_agent.config import get_settings

        if get_settings().deployment.mode != "saas":
            return

        from argus_agent.tenancy.context import get_tenant_id

        tenant_id = get_tenant_id()
        if tenant_id == "default":
            return
    except Exception:
        return

    policies = await _get_active_policies(tenant_id)
    if not policies:
        return

    # Collect unique contact user IDs from matching policies
    contact_ids: dict[str, str] = {}  # user_id -> policy_name (for email body)
    for policy in policies:
        if not _matches_policy(policy, event, alert.severity):
            continue
        policy_name = policy.get("name", "")
        for cid in (policy.get("primary_contact_id", ""), policy.get("backup_contact_id", "")):
            if cid and cid not in contact_ids:
                contact_ids[cid] = policy_name

    if not contact_ids:
        return

    friendly_message = format_event(event)

    for user_id, policy_name in contact_ids.items():
        email = await _resolve_user_email(user_id)
        if not email:
            continue

        plain, html = _render_escalation_email(
            alert, event, policy_name, friendly_message,
        )
        sev = _resolve_severity_str(alert.severity)
        subject = f"[Argus Escalation] {sev}: {alert.rule_name}"

        try:
            from argus_agent.auth.email import send_email

            await send_email(email, subject, plain, html=html)
            logger.info("Escalation email sent to %s for policy '%s'", email, policy_name)
        except Exception:
            logger.exception("Failed to send escalation email to %s", email)
