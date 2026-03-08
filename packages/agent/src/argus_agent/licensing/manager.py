"""License key validation and caching."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import jwt

from .editions import EDITION_ORDER, Edition, Feature
from .registry import FEATURE_REGISTRY

logger = logging.getLogger("argus.licensing")

# HMAC signing key — hardcoded for the foundation phase.
# Upgrade path: switch to RS256 where only the vendor holds the private key.
LICENSE_SIGNING_KEY = "argus-license-signing-key-v1"
LICENSE_ALGORITHM = "HS256"


@dataclass
class LicenseInfo:
    """Decoded license information."""

    edition: Edition = Edition.COMMUNITY
    holder: str = ""
    expires_at: datetime | None = None
    max_nodes: int = 1
    valid: bool = True
    error: str = ""
    features: list[Feature] = field(default_factory=list)


class LicenseManager:
    """Validates a license key and provides edition/feature information."""

    def __init__(self, license_key: str = "") -> None:
        self._key = license_key
        self._info = self._decode(license_key)

    def _decode(self, key: str) -> LicenseInfo:
        if not key:
            return self._community_fallback()

        try:
            payload = jwt.decode(
                key,
                LICENSE_SIGNING_KEY,
                algorithms=[LICENSE_ALGORITHM],
                options={"require": ["edition", "holder", "exp"]},
            )
        except jwt.ExpiredSignatureError:
            logger.warning("License key expired — falling back to Community")
            return self._community_fallback(error="expired")
        except jwt.InvalidTokenError as exc:
            logger.warning("Invalid license key (%s) — falling back to Community", exc)
            return self._community_fallback(error=str(exc))

        try:
            edition = Edition(payload["edition"])
        except ValueError:
            logger.warning("Unknown edition '%s' — falling back to Community", payload["edition"])
            return self._community_fallback(error="unknown_edition")

        info = LicenseInfo(
            edition=edition,
            holder=payload["holder"],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
            max_nodes=payload.get("max_nodes", 1),
            valid=True,
        )
        info.features = self._features_for(edition)
        return info

    def _community_fallback(self, error: str = "") -> LicenseInfo:
        info = LicenseInfo(
            edition=Edition.COMMUNITY,
            valid=error == "",
            error=error,
        )
        info.features = self._features_for(Edition.COMMUNITY)
        return info

    @staticmethod
    def _features_for(edition: Edition) -> list[Feature]:
        edition_level = EDITION_ORDER[edition]
        return [
            f for f, min_edition in FEATURE_REGISTRY.items()
            if EDITION_ORDER[min_edition] <= edition_level
        ]

    @property
    def info(self) -> LicenseInfo:
        return self._info

    @property
    def edition(self) -> Edition:
        return self._info.edition

    def get_enabled_features(self) -> list[Feature]:
        return list(self._info.features)

    def to_dict(self) -> dict:
        return {
            "edition": self._info.edition.value,
            "holder": self._info.holder,
            "expires_at": self._info.expires_at.isoformat() if self._info.expires_at else None,
            "max_nodes": self._info.max_nodes,
            "valid": self._info.valid,
            "error": self._info.error,
            "features": [f.value for f in self._info.features],
        }
