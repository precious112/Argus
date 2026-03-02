"""API key generation, hashing, and validation for SaaS mode."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

logger = logging.getLogger("argus.auth.api_keys")


def generate_api_key(environment: str = "production") -> tuple[str, str]:
    """Generate a new API key and its SHA-256 hash.

    Returns:
        (plain_key, key_hash) — the plain key is shown once, hash is stored.
    """
    random_part = secrets.token_urlsafe(32)
    prefix = f"argus_{environment[:4]}"
    plain_key = f"{prefix}_{random_part}"
    key_hash = hash_api_key(plain_key)
    return plain_key, key_hash


def hash_api_key(plain_key: str) -> str:
    """SHA-256 hash of a plain API key."""
    return hashlib.sha256(plain_key.encode()).hexdigest()


async def create_api_key(
    tenant_id: str,
    name: str = "",
    environment: str = "production",
) -> dict[str, Any]:
    """Create a new API key for a tenant. Returns the plain key (shown once).

    Inserts the key hash into the database using a session that bypasses
    RLS context (we set tenant_id directly on the row).
    """
    from argus_agent.storage.repositories import get_session
    from argus_agent.storage.saas_models import ApiKey

    plain_key, key_hash = generate_api_key(environment)
    prefix = plain_key[:16]  # first 16 chars as prefix for identification

    key_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)

    async with get_session() as session:
        # Set tenant context for RLS
        safe_tid = tenant_id.replace("'", "''")
        await session.execute(text(f"SET LOCAL app.current_tenant = '{safe_tid}'"))
        entry = ApiKey(
            id=key_id,
            tenant_id=tenant_id,
            name=name,
            key_prefix=prefix,
            key_hash=key_hash,
            environment=environment,
            is_active=True,
            created_at=now,
        )
        session.add(entry)
        await session.commit()

    logger.info("Created API key %s... for tenant %s", prefix, tenant_id)
    return {
        "key_id": key_id,
        "plain_key": plain_key,
        "key_prefix": prefix,
        "tenant_id": tenant_id,
        "name": name,
        "environment": environment,
    }


async def validate_api_key(plain_key: str) -> dict[str, Any] | None:
    """Validate a plain API key against the database.

    Returns ``{tenant_id, key_id, environment}`` on success, ``None`` on failure.

    Bypasses RLS for validation (we don't know the tenant_id yet) by
    setting ``app.current_tenant`` to empty string, which matches the
    ``api_key_lookup`` policy.
    """
    key_hash = hash_api_key(plain_key)

    from argus_agent.storage.repositories import get_session
    from argus_agent.storage.saas_models import ApiKey

    async with get_session() as session:
        # Bypass RLS — set empty tenant to use the api_key_lookup policy
        await session.execute(text("SET LOCAL app.current_tenant = ''"))  # noqa: S608

        stmt = select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active.is_(True),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            return None

        # Update last_used_at
        row.last_used_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()

        return {
            "tenant_id": row.tenant_id,
            "key_id": row.id,
            "environment": row.environment,
        }


async def revoke_api_key(key_id: str, tenant_id: str) -> bool:
    """Revoke an API key by marking it inactive."""
    from argus_agent.storage.repositories import get_session
    from argus_agent.storage.saas_models import ApiKey

    async with get_session() as session:
        safe_tid2 = tenant_id.replace("'", "''")
        await session.execute(
            text(f"SET LOCAL app.current_tenant = '{safe_tid2}'")
        )
        stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.is_active.is_(True))
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return False
        row.is_active = False
        row.revoked_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()
        return True
