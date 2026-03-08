"""JWT token creation and verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from argus_agent.config import get_settings


def create_access_token(
    user_id: str,
    username: str,
    tenant_id: str = "default",
    role: str = "member",
) -> str:
    """Create a signed JWT access token."""
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(hours=settings.security.session_expiry_hours)
    payload = {
        "sub": user_id,
        "username": username,
        "tenant_id": tenant_id,
        "role": role,
        "exp": expires,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.security.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises on invalid/expired."""
    settings = get_settings()
    return jwt.decode(token, settings.security.secret_key, algorithms=["HS256"])
