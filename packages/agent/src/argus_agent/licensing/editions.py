"""Edition tiers and gatable features for Argus open-core licensing."""

from __future__ import annotations

from enum import StrEnum


class Edition(StrEnum):
    """Argus product edition."""

    COMMUNITY = "community"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Feature(StrEnum):
    """All gatable features across editions."""

    # Community (included for completeness — always enabled)
    HOST_MONITORING = "host_monitoring"
    LOG_ANALYSIS = "log_analysis"
    BASIC_ALERTING = "basic_alerting"
    AI_CHAT = "ai_chat"
    SDK_TELEMETRY = "sdk_telemetry"

    # Pro
    TEAM_MANAGEMENT = "team_management"
    ADVANCED_INTEGRATIONS = "advanced_integrations"
    CUSTOM_DASHBOARDS = "custom_dashboards"
    PRIORITY_SUPPORT = "priority_support"

    # Enterprise
    MULTI_TENANCY = "multi_tenancy"
    SSO_SAML = "sso_saml"
    ADVANCED_ANALYTICS = "advanced_analytics"
    SLA_MONITORING = "sla_monitoring"
    AUDIT_LOG_EXPORT = "audit_log_export"


# Numeric ordering for tier comparison
EDITION_ORDER: dict[Edition, int] = {
    Edition.COMMUNITY: 0,
    Edition.PRO: 1,
    Edition.ENTERPRISE: 2,
}
