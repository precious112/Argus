"""Email integration API — per-user alert email opt-in for SaaS mode."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, update
from starlette.responses import JSONResponse

from argus_agent.auth.dependencies import require_role
from argus_agent.storage.models import User
from argus_agent.storage.repositories import get_session

logger = logging.getLogger("argus.api.email_integration")

router = APIRouter(
    prefix="/integrations/email",
    tags=["email-integration"],
)


class ToggleBody(BaseModel):
    enabled: bool


@router.get("/status")
async def email_status(user: dict = Depends(require_role("owner", "admin", "member"))) -> JSONResponse:
    """Return the current user's email alert preference."""
    user_id = user.get("sub", "")
    async with get_session() as session:
        result = await session.execute(
            select(User.email, User.email_alerts_enabled).where(User.id == user_id)
        )
        row = result.one_or_none()
        if not row:
            return JSONResponse({"enabled": False, "email": ""})
        return JSONResponse({"enabled": row[1], "email": row[0]})


@router.post("/toggle")
async def email_toggle(
    body: ToggleBody,
    user: dict = Depends(require_role("owner", "admin", "member")),
) -> JSONResponse:
    """Enable or disable email alerts for the current user."""
    user_id = user.get("sub", "")
    async with get_session() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(email_alerts_enabled=body.enabled)
        )
        await session.commit()
    return JSONResponse({"ok": True, "enabled": body.enabled})


@router.post("/test")
async def email_test(user: dict = Depends(require_role("owner", "admin", "member"))) -> JSONResponse:
    """Send a test alert email to the current user."""
    user_id = user.get("sub", "")
    async with get_session() as session:
        result = await session.execute(
            select(User.email).where(User.id == user_id)
        )
        row = result.one_or_none()
        if not row or not row[0]:
            return JSONResponse({"ok": False, "error": "No email address on file"}, status_code=400)
        email = row[0]

    from argus_agent.auth.email import send_email

    subject = "[Argus] Test Alert Email"
    body = (
        "This is a test alert email from Argus.\n\n"
        "If you received this, your email alerts are working correctly."
    )
    html = (
        "<html><body>"
        "<h2>Argus Test Alert</h2>"
        "<p>If you received this, your email alerts are working correctly.</p>"
        "</body></html>"
    )

    sent = await send_email(email, subject, body, html=html)
    if sent:
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "Failed to send email"}, status_code=500)
