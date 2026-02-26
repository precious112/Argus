"""Feature registry and gating functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from .editions import EDITION_ORDER, Edition, Feature

if TYPE_CHECKING:
    from collections.abc import Callable

    from .manager import LicenseManager

# Single source of truth: each feature -> minimum edition required
FEATURE_REGISTRY: dict[Feature, Edition] = {
    # Community features
    Feature.HOST_MONITORING: Edition.COMMUNITY,
    Feature.LOG_ANALYSIS: Edition.COMMUNITY,
    Feature.BASIC_ALERTING: Edition.COMMUNITY,
    Feature.AI_CHAT: Edition.COMMUNITY,
    Feature.SDK_TELEMETRY: Edition.COMMUNITY,
    # Pro features
    Feature.TEAM_MANAGEMENT: Edition.PRO,
    Feature.ADVANCED_INTEGRATIONS: Edition.PRO,
    Feature.CUSTOM_DASHBOARDS: Edition.PRO,
    Feature.PRIORITY_SUPPORT: Edition.PRO,
    # Enterprise features
    Feature.MULTI_TENANCY: Edition.ENTERPRISE,
    Feature.SSO_SAML: Edition.ENTERPRISE,
    Feature.ADVANCED_ANALYTICS: Edition.ENTERPRISE,
    Feature.SLA_MONITORING: Edition.ENTERPRISE,
    Feature.AUDIT_LOG_EXPORT: Edition.ENTERPRISE,
}

# ---------------------------------------------------------------------------
# Singleton license manager (mirrors get_settings() pattern)
# ---------------------------------------------------------------------------

_license_manager: LicenseManager | None = None


def get_license_manager() -> LicenseManager:
    """Get the global LicenseManager singleton."""
    global _license_manager
    if _license_manager is None:
        from ..config import get_settings
        from .manager import LicenseManager

        settings = get_settings()
        _license_manager = LicenseManager(settings.license.key)
    return _license_manager


def init_license_manager(key: str = "") -> LicenseManager:
    """Initialize the license manager with the given key."""
    global _license_manager
    from .manager import LicenseManager

    _license_manager = LicenseManager(key)
    return _license_manager


def reset_license_manager() -> None:
    """Reset the singleton (for testing)."""
    global _license_manager
    _license_manager = None


# ---------------------------------------------------------------------------
# Gating helpers
# ---------------------------------------------------------------------------


def has_feature(feature: Feature) -> bool:
    """Check if a feature is enabled in the current license. Pure dict lookup."""
    mgr = get_license_manager()
    required_edition = FEATURE_REGISTRY.get(feature, Edition.ENTERPRISE)
    current_level = EDITION_ORDER[mgr.edition]
    required_level = EDITION_ORDER[required_edition]
    return current_level >= required_level


def require_feature(feature: Feature) -> Callable:
    """Return a FastAPI ``Depends()`` callable that raises 403 if not licensed."""

    def _check() -> None:
        mgr = get_license_manager()
        required_edition = FEATURE_REGISTRY.get(feature, Edition.ENTERPRISE)
        current_level = EDITION_ORDER[mgr.edition]
        required_level = EDITION_ORDER[required_edition]
        if current_level < required_level:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "feature_not_licensed",
                    "feature": feature.value,
                    "required_edition": required_edition.value,
                    "current_edition": mgr.edition.value,
                },
            )

    return _check
