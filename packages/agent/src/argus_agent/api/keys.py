"""API key management endpoints (SaaS only)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from argus_agent.auth.api_keys import create_api_key, revoke_api_key
from argus_agent.auth.dependencies import require_role
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import ApiKey

logger = logging.getLogger("argus.api.keys")

router = APIRouter(prefix="/keys", tags=["api-keys"])


class CreateKeyRequest(BaseModel):
    name: str = ""
    environment: str = "production"


@router.get("")
async def list_keys(user: dict = Depends(require_role("owner", "admin"))):
    """List API keys for the current tenant (prefix + metadata only)."""
    tenant_id = user.get("tenant_id", "default")
    async with get_session() as session:
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.tenant_id == tenant_id,
                ApiKey.is_active.is_(True),
            )
        )
        keys = result.scalars().all()

    return [
        {
            "id": k.id,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "environment": k.environment,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in keys
    ]


@router.post("")
async def create_key(
    body: CreateKeyRequest,
    request: Request,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Create a new API key. The plain key is returned once."""
    from argus_agent.billing.usage_guard import check_api_key_limit

    await check_api_key_limit(request)

    tenant_id = user.get("tenant_id", "default")

    if body.environment not in ("production", "staging", "development"):
        raise HTTPException(400, "Environment must be 'production', 'staging', or 'development'")

    result = await create_api_key(
        tenant_id=tenant_id,
        name=body.name,
        environment=body.environment,
    )

    logger.info("API key created: %s for tenant %s", result["key_prefix"], tenant_id)
    return result


@router.delete("/{key_id}")
async def delete_key(key_id: str, user: dict = Depends(require_role("owner", "admin"))):
    """Revoke an API key."""
    tenant_id = user.get("tenant_id", "default")

    # Get the key hash before revoking (for cache invalidation)
    async with get_session() as session:
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.tenant_id == tenant_id,
            )
        )
        key = result.scalar_one_or_none()
        if not key:
            raise HTTPException(404, "API key not found")
        key_hash = key.key_hash

    success = await revoke_api_key(key_id, tenant_id)
    if not success:
        raise HTTPException(404, "API key not found or already revoked")

    # Invalidate Redis cache
    try:
        from argus_agent.auth.key_cache import invalidate_key

        await invalidate_key(key_hash)
    except Exception:
        logger.debug("Failed to invalidate key cache", exc_info=True)

    logger.info("API key revoked: %s for tenant %s", key_id, tenant_id)
    return {"status": "ok"}
