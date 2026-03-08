"""Investigations API — list, assign, and manage AI investigations."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from argus_agent.auth.dependencies import get_current_user
from argus_agent.storage.models import Investigation
from argus_agent.storage.repositories import get_session

logger = logging.getLogger("argus.investigations")

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.get("")
async def list_investigations(
    assigned_to: str | None = None,
    service: str | None = None,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_current_user),
):
    """List investigations with optional filters."""
    tenant_id = user.get("tenant_id", "default")
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    async with get_session() as session:
        query = select(Investigation).where(Investigation.tenant_id == tenant_id)

        if assigned_to:
            query = query.where(Investigation.assigned_to == assigned_to)
        if service:
            query = query.where(Investigation.service_name == service)

        query = query.order_by(Investigation.created_at.desc())

        # Count total
        from sqlalchemy import func

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar() or 0

        # Fetch page
        result = await session.execute(query.offset(offset).limit(page_size))
        investigations = result.scalars().all()

    items = [
        {
            "id": inv.id,
            "trigger": inv.trigger,
            "summary": inv.summary,
            "tokens_used": inv.tokens_used,
            "conversation_id": inv.conversation_id,
            "alert_id": inv.alert_id,
            "assigned_to": inv.assigned_to,
            "assigned_by": inv.assigned_by,
            "service_name": inv.service_name,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "completed_at": (
                inv.completed_at.isoformat() if inv.completed_at else None
            ),
        }
        for inv in investigations
    ]

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "investigations": items,
        "count": len(items),
        "total": total,
        "page": page,
        "total_pages": total_pages,
    }


class AssignRequest(BaseModel):
    assigned_to: str


@router.post("/{investigation_id}/assign")
async def assign_investigation(
    investigation_id: str,
    body: AssignRequest,
    user: dict = Depends(get_current_user),
):
    """Assign an investigation to a team member."""
    tenant_id = user.get("tenant_id", "default")
    user_id = user.get("sub", "")

    async with get_session() as session:
        result = await session.execute(
            select(Investigation).where(
                Investigation.id == investigation_id,
                Investigation.tenant_id == tenant_id,
            )
        )
        inv = result.scalar_one_or_none()
        if not inv:
            raise HTTPException(404, "Investigation not found")

        inv.assigned_to = body.assigned_to
        inv.assigned_by = user_id
        await session.commit()

    return {"status": "ok"}


@router.post("/{investigation_id}/unassign")
async def unassign_investigation(
    investigation_id: str,
    user: dict = Depends(get_current_user),
):
    """Remove assignment from an investigation."""
    tenant_id = user.get("tenant_id", "default")

    async with get_session() as session:
        await session.execute(
            update(Investigation)
            .where(
                Investigation.id == investigation_id,
                Investigation.tenant_id == tenant_id,
            )
            .values(assigned_to="", assigned_by="")
        )
        await session.commit()

    return {"status": "ok"}
