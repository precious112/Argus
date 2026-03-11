"""Authentication API endpoints."""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from argus_agent.auth.dependencies import get_current_user
from argus_agent.auth.jwt import create_access_token
from argus_agent.auth.password import hash_password, verify_password
from argus_agent.config import get_settings
from argus_agent.storage.models import User
from argus_agent.storage.repositories import get_session

logger = logging.getLogger("argus.auth")


def _cookie_kwargs(settings) -> dict:
    """Return cookie kwargs appropriate for the deployment mode.

    In SaaS mode the frontend and API live on different subdomains
    (e.g. app.tryargus.cloud / api.tryargus.cloud), so the cookie must
    be scoped to the shared parent domain and marked Secure.
    """
    from urllib.parse import urlparse

    base: dict = dict(
        key="argus_token",
        httponly=True,
        samesite="lax",
        path="/",
        max_age=settings.security.session_expiry_hours * 3600,
    )

    frontend_url = getattr(settings.deployment, "frontend_url", None)
    if settings.deployment.mode == "saas" and isinstance(frontend_url, str) and frontend_url:
        parsed = urlparse(frontend_url)
        hostname = parsed.hostname or ""
        # Extract parent domain: app.tryargus.cloud → .tryargus.cloud
        parts = hostname.split(".")
        if len(parts) >= 2:
            base["domain"] = "." + ".".join(parts[-2:])
        base["secure"] = True
        base["samesite"] = "none"

    return base

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_raw_session():
    """Return a raw AsyncSession (no RLS) for cross-tenant queries in SaaS mode."""
    from argus_agent.storage.postgres_operational import _engine

    if not _engine:
        return None

    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession(_engine, expire_on_commit=False)


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    """Verify credentials and set httpOnly JWT cookie."""
    settings = get_settings()

    # In SaaS mode, use raw engine session (no RLS) so global User lookup works
    if settings.deployment.mode == "saas":
        raw = _get_raw_session()
        if not raw:
            raise HTTPException(500, "Database not initialized")
        async with raw as session:
            result = await session.execute(
                select(User).where(User.username == body.username, User.is_active.is_(True))
            )
            user = result.scalar_one_or_none()
    else:
        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.username == body.username, User.is_active.is_(True))
            )
            user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        return Response(
            content='{"detail":"Invalid username or password"}',
            status_code=401,
            media_type="application/json",
        )

    # In SaaS mode, look up tenant membership for JWT claims
    tenant_id = "default"
    role = "member"
    if settings.deployment.mode == "saas":
        raw = _get_raw_session()
        if raw:
            async with raw as session:
                from argus_agent.storage.saas_models import TeamMember

                tm = await session.execute(
                    select(TeamMember).where(TeamMember.user_id == user.id)
                )
                member = tm.scalars().first()
                if member:
                    tenant_id = member.tenant_id
                    role = member.role

    token = create_access_token(user.id, user.username, tenant_id, role)
    max_age = settings.security.session_expiry_hours * 3600

    response = Response(
        content='{"status":"ok"}',
        media_type="application/json",
    )
    response.set_cookie(value=token, **_cookie_kwargs(settings))
    return response


@router.post("/logout")
async def logout(response: Response):
    """Clear the auth cookie."""
    response = Response(
        content='{"status":"ok"}',
        media_type="application/json",
    )
    ck = _cookie_kwargs(get_settings())
    response.delete_cookie(
        key="argus_token",
        path="/",
        domain=ck.get("domain"),
        samesite=ck.get("samesite", "lax"),
        secure=ck.get("secure", False),
    )
    return response


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Return the current authenticated user info."""
    return {
        "user_id": user.get("sub"),
        "username": user.get("username"),
        "tenant_id": user.get("tenant_id", "default"),
        "role": user.get("role", "member"),
    }


class CreateOrgRequest(BaseModel):
    org_name: str


@router.post("/create-org")
async def create_org(
    body: CreateOrgRequest,
    response: Response,
    user: dict = Depends(get_current_user),
):
    """Create a new organization for the current user (SaaS only)."""
    settings = get_settings()
    if settings.deployment.mode != "saas":
        raise HTTPException(400, "Not available in self-hosted mode")

    from argus_agent.storage.saas_models import TeamMember, Tenant

    raw = _get_raw_session()
    if not raw:
        raise HTTPException(500, "Database not initialized")

    user_id = user.get("sub")
    tenant_id = str(uuid.uuid4())
    slug = re.sub(r"[^a-z0-9]+", "-", body.org_name.lower()).strip("-")[:50]
    slug = f"{slug or 'org'}-{uuid.uuid4().hex[:8]}"

    async with raw as session:
        tenant = Tenant(id=tenant_id, name=body.org_name, slug=slug)
        session.add(tenant)

        member = TeamMember(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            role="owner",
        )
        session.add(member)

        await session.commit()

    logger.info("User %s created org %s (%s)", user_id, body.org_name, tenant_id)
    return {"tenant_id": tenant_id, "tenant_name": body.org_name}


@router.get("/organizations")
async def list_organizations(user: dict = Depends(get_current_user)):
    """List all organizations the current user belongs to."""
    settings = get_settings()
    if settings.deployment.mode != "saas":
        return []

    current_tenant = user.get("tenant_id", "default")
    user_id = user.get("sub")

    from argus_agent.storage.saas_models import TeamMember, Tenant

    raw = _get_raw_session()
    if not raw:
        return []

    async with raw as session:
        result = await session.execute(
            select(TeamMember, Tenant)
            .join(Tenant, Tenant.id == TeamMember.tenant_id)
            .where(TeamMember.user_id == user_id)
        )
        rows = result.all()

    return [
        {
            "tenant_id": tenant.id,
            "tenant_name": tenant.name,
            "role": tm.role,
            "is_current": tenant.id == current_tenant,
        }
        for tm, tenant in rows
    ]


class SwitchOrgRequest(BaseModel):
    tenant_id: str


@router.post("/switch-org")
async def switch_org(
    body: SwitchOrgRequest,
    response: Response,
    user: dict = Depends(get_current_user),
):
    """Switch to a different organization by issuing a new JWT."""
    settings = get_settings()
    if settings.deployment.mode != "saas":
        raise HTTPException(400, "Not available in self-hosted mode")

    from argus_agent.storage.saas_models import TeamMember

    user_id = user.get("sub")
    raw = _get_raw_session()
    if not raw:
        raise HTTPException(500, "Database not initialized")

    async with raw as session:
        # Verify the user is a member of the target org
        result = await session.execute(
            select(TeamMember).where(
                TeamMember.user_id == user_id,
                TeamMember.tenant_id == body.tenant_id,
            )
        )
        tm = result.scalar_one_or_none()

    if not tm:
        raise HTTPException(403, "You are not a member of that organization")

    # Same user_id, same username — just reissue JWT with the target tenant
    token = create_access_token(user_id, user.get("username", ""), tm.tenant_id, tm.role)
    max_age = settings.security.session_expiry_hours * 3600

    response = Response(
        content='{"status":"ok"}',
        media_type="application/json",
    )
    response.set_cookie(value=token, **_cookie_kwargs(settings))
    return response


# ---- Email Verification ----


class VerifyEmailRequest(BaseModel):
    token: str


@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest):
    """Verify an email address using the token from the email link."""
    settings = get_settings()
    if settings.deployment.mode != "saas":
        raise HTTPException(400, "Not available in self-hosted mode")

    from argus_agent.auth.email import verify_email_token

    result = await verify_email_token(body.token)
    if not result["ok"]:
        raise HTTPException(400, result["error"])

    return {"status": "ok", "message": "Email verified successfully"}


class ResendVerificationRequest(BaseModel):
    email: EmailStr


@router.post("/resend-verification")
async def resend_verification(body: ResendVerificationRequest):
    """Resend the verification email."""
    settings = get_settings()
    if settings.deployment.mode != "saas":
        raise HTTPException(400, "Not available in self-hosted mode")

    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.email == body.email, User.is_active.is_(True))
        )
        user = result.scalar_one_or_none()

    if user and not user.email_verified:
        from argus_agent.auth.email import send_verification_email

        await send_verification_email(user.id, user.email)

    # Always return success to not reveal if email exists
    return {"status": "ok", "message": "If the email exists, a verification link has been sent"}


# ---- Password Reset ----


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """Send a password reset email."""
    settings = get_settings()
    if settings.deployment.mode != "saas":
        raise HTTPException(400, "Not available in self-hosted mode")

    from argus_agent.auth.email import send_password_reset_email

    await send_password_reset_email(body.email)

    return {"status": "ok", "message": "If the email exists, a reset link has been sent"}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """Reset password using a valid token."""
    settings = get_settings()
    if settings.deployment.mode != "saas":
        raise HTTPException(400, "Not available in self-hosted mode")

    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    from argus_agent.auth.email import consume_reset_token

    result = await consume_reset_token(body.token, hash_password(body.new_password))
    if not result["ok"]:
        raise HTTPException(400, result["error"])

    return {"status": "ok", "message": "Password reset successfully"}
