"""BYOK LLM key management API — per-tenant encrypted key storage."""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from argus_agent.auth.dependencies import get_current_user, require_role
from argus_agent.config import get_settings
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import TenantLLMConfig

logger = logging.getLogger("argus.llm_keys")

router = APIRouter(prefix="/llm-config", tags=["llm-config"])


def _derive_key(secret: str, tenant_id: str) -> bytes:
    """Derive a tenant-specific encryption key from the server secret."""
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), tenant_id.encode(), 100_000)


def _encrypt(plaintext: str, key: bytes) -> str:
    """Simple XOR + base64 encryption. Sufficient for at-rest key storage."""
    if not plaintext:
        return ""
    pt_bytes = plaintext.encode()
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(pt_bytes))
    return base64.b64encode(encrypted).decode()


def _decrypt(ciphertext: str, key: bytes) -> str:
    """Decrypt a value encrypted with _encrypt."""
    if not ciphertext:
        return ""
    ct_bytes = base64.b64decode(ciphertext)
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(ct_bytes))
    return decrypted.decode()


class LLMConfigRequest(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    model: str = ""
    base_url: str = ""


@router.get("")
async def get_llm_config(user: dict = Depends(get_current_user)):
    """Get the tenant's LLM configuration (key is masked)."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(TenantLLMConfig).where(TenantLLMConfig.tenant_id == tenant_id)
        )
        config = result.scalar_one_or_none()

    if not config:
        return {
            "configured": False,
            "provider": "",
            "model": "",
            "base_url": "",
            "has_api_key": False,
        }

    return {
        "configured": True,
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "has_api_key": bool(config.encrypted_api_key),
    }


@router.put("")
async def set_llm_config(
    body: LLMConfigRequest,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Set or update the tenant's LLM configuration."""
    tenant_id = user.get("tenant_id", "default")
    settings = get_settings()
    enc_key = _derive_key(settings.security.secret_key, tenant_id)

    encrypted_key = _encrypt(body.api_key, enc_key) if body.api_key else ""

    async with get_session() as session:
        result = await session.execute(
            select(TenantLLMConfig).where(TenantLLMConfig.tenant_id == tenant_id)
        )
        config = result.scalar_one_or_none()

        if config:
            config.provider = body.provider
            config.model = body.model
            config.base_url = body.base_url
            if body.api_key:
                config.encrypted_api_key = encrypted_key
        else:
            config = TenantLLMConfig(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                provider=body.provider,
                encrypted_api_key=encrypted_key,
                model=body.model,
                base_url=body.base_url,
            )
            session.add(config)

        await session.commit()

    logger.info("Updated LLM config for tenant %s", tenant_id)
    return {"status": "ok"}


@router.delete("")
async def delete_llm_config(
    user: dict = Depends(require_role("owner", "admin")),
):
    """Delete the tenant's custom LLM configuration (reverts to platform default)."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(TenantLLMConfig).where(TenantLLMConfig.tenant_id == tenant_id)
        )
        config = result.scalar_one_or_none()
        if config:
            await session.delete(config)
            await session.commit()

    return {"status": "ok"}


async def get_tenant_llm_key(tenant_id: str) -> dict | None:
    """Get the decrypted LLM config for a tenant. Used internally by the agent."""
    settings = get_settings()
    enc_key = _derive_key(settings.security.secret_key, tenant_id)

    async with get_session() as session:
        result = await session.execute(
            select(TenantLLMConfig).where(TenantLLMConfig.tenant_id == tenant_id)
        )
        config = result.scalar_one_or_none()

    if not config or not config.encrypted_api_key:
        return None

    return {
        "provider": config.provider,
        "api_key": _decrypt(config.encrypted_api_key, enc_key),
        "model": config.model,
        "base_url": config.base_url,
    }
