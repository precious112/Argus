"""SaaS registration endpoint — create tenant + owner user in one transaction."""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from argus_agent.auth.jwt import create_access_token
from argus_agent.auth.password import hash_password
from argus_agent.config import get_settings
from argus_agent.storage.models import User
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import TeamMember, Tenant

logger = logging.getLogger("argus.auth.registration")

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    org_name: str


def _slugify(name: str) -> str:
    """Convert an org name to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:100] if slug else "org"


@router.post("/register")
async def register(body: RegisterRequest, response: Response):
    """Register a new user and create their tenant (SaaS only)."""
    settings = get_settings()
    if settings.deployment.mode != "saas":
        raise HTTPException(400, "Registration disabled in self-hosted mode")

    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    slug = f"{_slugify(body.org_name)}-{uuid.uuid4().hex[:8]}"

    async with get_session() as session:
        # Check for existing username
        existing = await session.execute(
            select(User).where(User.username == body.username)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Username already taken")

        # Check for existing email
        existing_email = await session.execute(
            select(User).where(User.email == body.email)
        )
        if existing_email.scalar_one_or_none():
            raise HTTPException(409, "Email already registered")

        # 1. Create Tenant
        tenant = Tenant(
            id=tenant_id,
            name=body.org_name,
            slug=slug,
        )
        session.add(tenant)

        # 2. Create User
        user = User(
            id=user_id,
            tenant_id=tenant_id,
            username=body.username,
            email=body.email,
            password_hash=hash_password(body.password),
        )
        session.add(user)

        # 3. Create TeamMember (owner)
        member = TeamMember(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            role="owner",
        )
        session.add(member)

        await session.commit()

    # 4. Issue JWT
    token = create_access_token(user_id, body.username, tenant_id, "owner")
    max_age = settings.security.session_expiry_hours * 3600

    response = Response(
        content='{"status":"ok","message":"Registration successful"}',
        media_type="application/json",
    )
    response.set_cookie(
        key="argus_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=max_age,
    )

    logger.info("Registered user %s with tenant %s", body.username, tenant_id)
    return response
