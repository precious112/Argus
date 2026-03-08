"""Service configuration API — ownership, environment, escalation policies."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from argus_agent.auth.dependencies import get_current_user, require_role
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import EscalationPolicy, ServiceConfig

logger = logging.getLogger("argus.service_config")

router = APIRouter(prefix="/service-configs", tags=["service-configs"])


# ---- Service Configs ----


class ServiceConfigRequest(BaseModel):
    service_name: str
    environment: str = "production"
    owner_user_id: str = ""
    description: str = ""


@router.get("")
async def list_service_configs(user: dict = Depends(get_current_user)):
    """List all service configurations for the tenant."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(ServiceConfig).where(ServiceConfig.tenant_id == tenant_id)
        )
        configs = result.scalars().all()

    return {
        "configs": [
            {
                "id": c.id,
                "service_name": c.service_name,
                "environment": c.environment,
                "owner_user_id": c.owner_user_id,
                "description": c.description,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in configs
        ],
    }


@router.put("/{service_name}")
async def upsert_service_config(
    service_name: str,
    body: ServiceConfigRequest,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Create or update a service configuration."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(ServiceConfig).where(
                ServiceConfig.tenant_id == tenant_id,
                ServiceConfig.service_name == service_name,
            )
        )
        config = result.scalar_one_or_none()

        if config:
            config.environment = body.environment
            config.owner_user_id = body.owner_user_id
            config.description = body.description
        else:
            config = ServiceConfig(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                service_name=service_name,
                environment=body.environment,
                owner_user_id=body.owner_user_id,
                description=body.description,
            )
            session.add(config)

        await session.commit()

    return {"status": "ok"}


@router.delete("/{service_name}")
async def delete_service_config(
    service_name: str,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Delete a service configuration."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(ServiceConfig).where(
                ServiceConfig.tenant_id == tenant_id,
                ServiceConfig.service_name == service_name,
            )
        )
        config = result.scalar_one_or_none()
        if config:
            await session.delete(config)
            await session.commit()

    return {"status": "ok"}


# ---- Escalation Policies ----


class EscalationPolicyRequest(BaseModel):
    name: str
    service_name: str = ""
    min_severity: str = ""
    primary_contact_id: str = ""
    backup_contact_id: str = ""


escalation_router = APIRouter(prefix="/escalation-policies", tags=["escalation"])


@escalation_router.get("")
async def list_escalation_policies(user: dict = Depends(get_current_user)):
    """List all escalation policies for the tenant."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(EscalationPolicy).where(
                EscalationPolicy.tenant_id == tenant_id,
                EscalationPolicy.is_active.is_(True),
            )
        )
        policies = result.scalars().all()

    return {
        "policies": [
            {
                "id": p.id,
                "name": p.name,
                "service_name": p.service_name,
                "min_severity": p.min_severity,
                "primary_contact_id": p.primary_contact_id,
                "backup_contact_id": p.backup_contact_id,
                "is_active": p.is_active,
            }
            for p in policies
        ],
    }


@escalation_router.post("")
async def create_escalation_policy(
    body: EscalationPolicyRequest,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Create an escalation policy."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        policy = EscalationPolicy(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=body.name,
            service_name=body.service_name,
            min_severity=body.min_severity,
            primary_contact_id=body.primary_contact_id,
            backup_contact_id=body.backup_contact_id,
        )
        session.add(policy)
        await session.commit()

    return {"status": "ok", "id": policy.id}


@escalation_router.put("/{policy_id}")
async def update_escalation_policy(
    policy_id: str,
    body: EscalationPolicyRequest,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Update an escalation policy."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(EscalationPolicy).where(
                EscalationPolicy.id == policy_id,
                EscalationPolicy.tenant_id == tenant_id,
            )
        )
        policy = result.scalar_one_or_none()
        if not policy:
            raise HTTPException(404, "Policy not found")

        policy.name = body.name
        policy.service_name = body.service_name
        policy.min_severity = body.min_severity
        policy.primary_contact_id = body.primary_contact_id
        policy.backup_contact_id = body.backup_contact_id
        await session.commit()

    return {"status": "ok"}


@escalation_router.delete("/{policy_id}")
async def delete_escalation_policy(
    policy_id: str,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Delete (deactivate) an escalation policy."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        result = await session.execute(
            select(EscalationPolicy).where(
                EscalationPolicy.id == policy_id,
                EscalationPolicy.tenant_id == tenant_id,
            )
        )
        policy = result.scalar_one_or_none()
        if policy:
            policy.is_active = False
            await session.commit()

    return {"status": "ok"}
