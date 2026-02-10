"""Audit logging for all executed actions."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from argus_agent.storage.database import get_session
from argus_agent.storage.models import AuditLog

logger = logging.getLogger("argus.actions.audit")


class AuditLogger:
    """Persist action audit entries to the database."""

    async def log_action(
        self,
        action: str,
        command: str = "",
        result: str = "",
        success: bool = True,
        user_approved: bool = False,
        ip_address: str = "",
        conversation_id: str = "",
    ) -> int:
        """Log an action to the audit trail. Returns the entry ID."""
        async with get_session() as session:
            entry = AuditLog(
                action=action,
                command=command,
                result=result,
                success=success,
                user_approved=user_approved,
                ip_address=ip_address,
                conversation_id=conversation_id,
            )
            session.add(entry)
            await session.flush()
            entry_id = entry.id
            await session.commit()
            logger.info("Audit log #%d: action=%s success=%s", entry_id, action, success)
            return entry_id

    async def get_audit_log(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get paginated audit log entries."""
        async with get_session() as session:
            stmt = (
                select(AuditLog)
                .order_by(AuditLog.timestamp.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "id": row.id,
                    "timestamp": row.timestamp.isoformat(),
                    "action": row.action,
                    "command": row.command,
                    "result": row.result,
                    "success": row.success,
                    "user_approved": row.user_approved,
                    "ip_address": row.ip_address,
                    "conversation_id": row.conversation_id,
                }
                for row in rows
            ]
