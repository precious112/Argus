"""Authentication API endpoints."""

from __future__ import annotations

import logging

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

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    """Verify credentials and set httpOnly JWT cookie."""
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.username == body.username, User.is_active.is_(True))
        )
        user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        return Response(
            content='{"detail":"Invalid username or password"}',
            status_code=401,
            media_type="application/json",
        )

    # In SaaS mode, look up tenant membership for JWT claims
    tenant_id = "default"
    role = "member"
    settings = get_settings()
    if settings.deployment.mode == "saas":
        async with get_session() as session:
            from argus_agent.storage.saas_models import TeamMember

            tm = await session.execute(
                select(TeamMember).where(TeamMember.user_id == user.id)
            )
            member = tm.scalar_one_or_none()
            if member:
                tenant_id = member.tenant_id
                role = member.role

    token = create_access_token(user.id, user.username, tenant_id, role)
    max_age = settings.security.session_expiry_hours * 3600

    response = Response(
        content='{"status":"ok"}',
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
    return response


@router.post("/logout")
async def logout(response: Response):
    """Clear the auth cookie."""
    response = Response(
        content='{"status":"ok"}',
        media_type="application/json",
    )
    response.delete_cookie(key="argus_token", path="/")
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
