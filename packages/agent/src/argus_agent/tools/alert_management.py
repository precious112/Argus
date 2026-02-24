"""Alert management tools — acknowledge, mute, and list alert rules."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.alert_management")


class AcknowledgeAlertTool(Tool):
    """Acknowledge an alert by ID, suppressing future re-fires for the same condition."""

    @property
    def name(self) -> str:
        return "acknowledge_alert"

    @property
    def description(self) -> str:
        return (
            "Acknowledge an alert by ID. This marks the alert as acknowledged and "
            "suppresses future alerts for the same condition (dedup key). "
            "Optionally set an expiry in hours (default: permanent)."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.LOW

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "alert_id": {
                    "type": "string",
                    "description": "The alert ID to acknowledge",
                },
                "expires_hours": {
                    "type": "number",
                    "description": "Hours until acknowledgment expires (omit for permanent)",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for acknowledging",
                },
            },
            "required": ["alert_id"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        from argus_agent.alerting.suppression import SuppressionService
        from argus_agent.main import _get_alert_engine

        engine = _get_alert_engine()
        if engine is None:
            return {"error": "Alert engine not initialized"}

        alert_id = kwargs["alert_id"]
        expires_hours = kwargs.get("expires_hours")
        reason = kwargs.get("reason", "")

        expires_at = None
        if expires_hours is not None:
            expires_at = datetime.now(UTC) + timedelta(hours=float(expires_hours))

        success = engine.acknowledge_alert(
            alert_id, acknowledged_by="ai", expires_at=expires_at,
        )
        if not success:
            return {"error": f"Alert {alert_id} not found"}

        # Persist
        alert = next((a for a in engine._active_alerts if a.id == alert_id), None)
        if alert:
            dedup_key = f"{alert.event.source}:{alert.rule_id}"
            svc = SuppressionService()
            await svc.acknowledge(
                dedup_key=dedup_key,
                rule_id=alert.rule_id,
                source=str(alert.event.source),
                acknowledged_by="ai",
                reason=reason,
                expires_at=expires_at,
            )

        return {
            "status": "acknowledged",
            "alert_id": alert_id,
            "expires_at": expires_at.isoformat() if expires_at else "permanent",
        }


class MuteAlertRuleTool(Tool):
    """Mute an alert rule by ID for a specified duration."""

    @property
    def name(self) -> str:
        return "mute_alert_rule"

    @property
    def description(self) -> str:
        return (
            "Mute an alert rule by ID for a specified duration. "
            "While muted, no alerts will fire for this rule. "
            "Maximum duration is 168 hours (7 days)."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.LOW

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rule_id": {
                    "type": "string",
                    "description": "The rule ID to mute",
                },
                "duration_hours": {
                    "type": "number",
                    "description": "Hours to mute the rule (default 24, max 168)",
                    "default": 24,
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for muting",
                },
            },
            "required": ["rule_id"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        from argus_agent.alerting.suppression import SuppressionService
        from argus_agent.main import _get_alert_engine

        engine = _get_alert_engine()
        if engine is None:
            return {"error": "Alert engine not initialized"}

        rule_id = kwargs["rule_id"]
        duration_hours = min(float(kwargs.get("duration_hours", 24)), 168)
        reason = kwargs.get("reason", "")

        expires_at = datetime.now(UTC) + timedelta(hours=duration_hours)
        success = engine.mute_rule(rule_id, expires_at)
        if not success:
            return {"error": f"Rule {rule_id} not found"}

        # Persist
        svc = SuppressionService()
        await svc.mute_rule(
            rule_id=rule_id,
            muted_by="ai",
            reason=reason,
            expires_at=expires_at,
        )

        return {
            "status": "muted",
            "rule_id": rule_id,
            "duration_hours": duration_hours,
            "expires_at": expires_at.isoformat(),
        }


class ListAlertRulesTool(Tool):
    """List all alert rules and their current status."""

    @property
    def name(self) -> str:
        return "list_alert_rules"

    @property
    def description(self) -> str:
        return (
            "List all alert rules with their configuration and current mute status. "
            "Use this to see which rules are active, muted, and their settings."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        from argus_agent.main import _get_alert_engine

        engine = _get_alert_engine()
        if engine is None:
            return {"error": "Alert engine not initialized"}

        rules = engine.get_rules()
        muted = engine.get_muted_rules()
        ack_keys = engine.get_acknowledged_keys()

        items = []
        for rule in rules.values():
            mute_expires = muted.get(rule.id)
            items.append({
                "id": rule.id,
                "name": rule.name,
                "event_types": rule.event_types,
                "min_severity": str(rule.min_severity),
                "cooldown_seconds": rule.cooldown_seconds,
                "auto_investigate": rule.auto_investigate,
                "muted": rule.id in muted,
                "mute_expires_at": mute_expires.isoformat() if mute_expires else None,
            })

        return {
            "rules": items,
            "count": len(items),
            "acknowledged_keys_count": len(ack_keys),
            "muted_rules_count": len(muted),
        }


def register_alert_management_tools() -> None:
    """Register alert management tools."""
    from argus_agent.tools.base import register_tool

    register_tool(AcknowledgeAlertTool())
    register_tool(MuteAlertRuleTool())
    register_tool(ListAlertRulesTool())
