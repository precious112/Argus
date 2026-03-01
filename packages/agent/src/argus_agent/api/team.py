"""Team management endpoints (SaaS only)."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from argus_agent.auth.dependencies import require_role
from argus_agent.auth.jwt import create_access_token
from argus_agent.auth.password import hash_password
from argus_agent.storage.models import User
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import TeamInvitation, TeamMember

logger = logging.getLogger("argus.api.team")

router = APIRouter(prefix="/team", tags=["team"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"


class UpdateRoleRequest(BaseModel):
    role: str


class AcceptInviteRequest(BaseModel):
    token: str
    username: str
    password: str


# ---------------------------------------------------------------------------
# Team member endpoints (require owner/admin)
# ---------------------------------------------------------------------------

@router.get("/members")
async def list_members(user: dict = Depends(require_role("owner", "admin"))):
    """List team members for the current tenant."""
    tenant_id = user.get("tenant_id", "default")
    async with get_session() as session:
        result = await session.execute(
            select(TeamMember).where(TeamMember.tenant_id == tenant_id)
        )
        members = result.scalars().all()

        # Fetch user info for each member
        user_ids = [m.user_id for m in members]
        users_result = await session.execute(
            select(User).where(User.id.in_(user_ids))
        )
        users_map = {u.id: u for u in users_result.scalars().all()}

    return [
        {
            "id": m.id,
            "user_id": m.user_id,
            "username": users_map[m.user_id].username if m.user_id in users_map else "",
            "email": users_map[m.user_id].email if m.user_id in users_map else "",
            "role": m.role,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
        }
        for m in members
    ]


@router.post("/invite")
async def invite_member(
    body: InviteRequest,
    request: Request,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Create an invitation to join the tenant."""
    from argus_agent.billing.usage_guard import check_team_member_limit

    await check_team_member_limit(request)

    tenant_id = user.get("tenant_id", "default")

    if body.role not in ("member", "admin"):
        raise HTTPException(400, "Role must be 'member' or 'admin'")

    # Generate invitation token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    async with get_session() as session:
        # Check for existing pending invitation
        existing = await session.execute(
            select(TeamInvitation).where(
                TeamInvitation.tenant_id == tenant_id,
                TeamInvitation.email == body.email,
                TeamInvitation.accepted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Invitation already pending for this email")

        invitation = TeamInvitation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=body.email,
            role=body.role,
            invited_by=user.get("sub", ""),
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(invitation)
        await session.commit()

    logger.info("Invitation created for %s to tenant %s", body.email, tenant_id)
    return {
        "id": invitation.id,
        "email": body.email,
        "role": body.role,
        "token": raw_token,
        "expires_at": invitation.expires_at.isoformat(),
    }


@router.delete("/members/{user_id}")
async def remove_member(user_id: str, user: dict = Depends(require_role("owner", "admin"))):
    """Remove a member from the tenant."""
    tenant_id = user.get("tenant_id", "default")

    if user_id == user.get("sub"):
        raise HTTPException(400, "Cannot remove yourself")

    async with get_session() as session:
        result = await session.execute(
            select(TeamMember).where(
                TeamMember.tenant_id == tenant_id,
                TeamMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise HTTPException(404, "Member not found")

        if member.role == "owner":
            raise HTTPException(400, "Cannot remove the owner")

        await session.delete(member)

        # Deactivate the user
        user_result = await session.execute(
            select(User).where(User.id == user_id)
        )
        target_user = user_result.scalar_one_or_none()
        if target_user:
            target_user.is_active = False

        await session.commit()

    return {"status": "ok"}


@router.put("/members/{user_id}/role")
async def update_member_role(
    user_id: str,
    body: UpdateRoleRequest,
    user: dict = Depends(require_role("owner")),
):
    """Update a member's role (owner only)."""
    tenant_id = user.get("tenant_id", "default")

    if body.role not in ("member", "admin"):
        raise HTTPException(400, "Role must be 'member' or 'admin'")

    if user_id == user.get("sub"):
        raise HTTPException(400, "Cannot change your own role")

    async with get_session() as session:
        result = await session.execute(
            select(TeamMember).where(
                TeamMember.tenant_id == tenant_id,
                TeamMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise HTTPException(404, "Member not found")

        member.role = body.role
        await session.commit()

    return {"status": "ok", "role": body.role}


# ---------------------------------------------------------------------------
# Invitation management
# ---------------------------------------------------------------------------

@router.get("/invitations")
async def list_invitations(user: dict = Depends(require_role("owner", "admin"))):
    """List pending invitations for the current tenant."""
    tenant_id = user.get("tenant_id", "default")
    async with get_session() as session:
        result = await session.execute(
            select(TeamInvitation).where(
                TeamInvitation.tenant_id == tenant_id,
                TeamInvitation.accepted_at.is_(None),
            )
        )
        invitations = result.scalars().all()

    return [
        {
            "id": inv.id,
            "email": inv.email,
            "role": inv.role,
            "invited_by": inv.invited_by,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invitations
    ]


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: str,
    user: dict = Depends(require_role("owner", "admin")),
):
    """Revoke a pending invitation."""
    tenant_id = user.get("tenant_id", "default")
    async with get_session() as session:
        result = await session.execute(
            select(TeamInvitation).where(
                TeamInvitation.id == invitation_id,
                TeamInvitation.tenant_id == tenant_id,
                TeamInvitation.accepted_at.is_(None),
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(404, "Invitation not found")

        await session.delete(invitation)
        await session.commit()

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Public: accept invitation (mounted under /auth prefix in main.py)
# ---------------------------------------------------------------------------

accept_router = APIRouter(prefix="/auth", tags=["auth"])


@accept_router.post("/accept-invite")
async def accept_invite(body: AcceptInviteRequest, response: Response):
    """Accept an invitation token, create user, and join the tenant."""
    from argus_agent.config import get_settings

    settings = get_settings()
    if settings.deployment.mode != "saas":
        raise HTTPException(400, "Invitations not available in self-hosted mode")

    token_hash = hashlib.sha256(body.token.encode()).hexdigest()

    async with get_session() as session:
        result = await session.execute(
            select(TeamInvitation).where(
                TeamInvitation.token_hash == token_hash,
                TeamInvitation.accepted_at.is_(None),
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(404, "Invalid or expired invitation")

        if invitation.expires_at and invitation.expires_at < datetime.now(UTC):
            raise HTTPException(410, "Invitation has expired")

        # Check username availability
        existing = await session.execute(
            select(User).where(
                User.username == body.username,
                User.tenant_id == invitation.tenant_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Username already taken in this organization")

        # Create user
        user_id = str(uuid.uuid4())
        new_user = User(
            id=user_id,
            tenant_id=invitation.tenant_id,
            username=body.username,
            email=invitation.email,
            password_hash=hash_password(body.password),
        )
        session.add(new_user)

        # Create team member
        member = TeamMember(
            id=str(uuid.uuid4()),
            tenant_id=invitation.tenant_id,
            user_id=user_id,
            role=invitation.role,
        )
        session.add(member)

        # Mark invitation as accepted
        invitation.accepted_at = datetime.now(UTC)

        await session.commit()

    # Issue JWT
    token = create_access_token(
        user_id, body.username, invitation.tenant_id, invitation.role,
    )
    max_age = settings.security.session_expiry_hours * 3600

    response = Response(
        content='{"status":"ok","message":"Invitation accepted"}',
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

    logger.info("User %s accepted invitation to tenant %s", body.username, invitation.tenant_id)
    return response
