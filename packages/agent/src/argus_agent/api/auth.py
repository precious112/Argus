"""Authentication API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select

from argus_agent.auth.dependencies import get_current_user
from argus_agent.auth.jwt import create_access_token
from argus_agent.auth.password import verify_password
from argus_agent.config import get_settings
from argus_agent.storage.database import get_session
from argus_agent.storage.models import User

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

    token = create_access_token(user.id, user.username)
    settings = get_settings()
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
    }
