"""Argus licensing system — open-core edition and feature gating."""

from .editions import EDITION_ORDER, Edition, Feature
from .keygen import generate_license_key
from .manager import LicenseInfo, LicenseManager
from .registry import (
    FEATURE_REGISTRY,
    get_license_manager,
    has_feature,
    init_license_manager,
    require_feature,
    reset_license_manager,
)

__all__ = [
    "EDITION_ORDER",
    "Edition",
    "FEATURE_REGISTRY",
    "Feature",
    "LicenseInfo",
    "LicenseManager",
    "generate_license_key",
    "get_license_manager",
    "has_feature",
    "init_license_manager",
    "require_feature",
    "reset_license_manager",
]
