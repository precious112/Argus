"""License key generation utility.

Vendor-side tool for creating signed license keys. In production,
this would live in a separate admin service — included here for
development and testing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from .editions import Edition
from .manager import LICENSE_ALGORITHM, LICENSE_SIGNING_KEY


def generate_license_key(
    edition: Edition | str,
    holder: str,
    expires_days: int = 365,
    max_nodes: int = 1,
) -> str:
    """Generate a signed license key JWT.

    Args:
        edition: The edition tier (community, pro, enterprise).
        holder: The license holder name / org.
        expires_days: Days until the license expires.
        max_nodes: Maximum number of monitored nodes.

    Returns:
        Signed JWT string.
    """
    if isinstance(edition, str):
        edition = Edition(edition)

    now = datetime.now(UTC)
    payload = {
        "edition": edition.value,
        "holder": holder,
        "iat": now,
        "exp": now + timedelta(days=expires_days),
        "max_nodes": max_nodes,
    }
    return jwt.encode(payload, LICENSE_SIGNING_KEY, algorithm=LICENSE_ALGORITHM)
