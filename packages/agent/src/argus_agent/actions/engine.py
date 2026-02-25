"""Action execution pipeline: approve → execute → audit → report."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from argus_agent.actions.audit import AuditLogger
from argus_agent.actions.sandbox import CommandResult, CommandSandbox
from argus_agent.api.protocol import ServerMessage, ServerMessageType
from argus_agent.tools.base import ToolRisk

logger = logging.getLogger("argus.actions.engine")

# Timeout waiting for user approval (seconds)
APPROVAL_TIMEOUT = 300  # 5 minutes


@dataclass
class ActionResult:
    """Outcome of a proposed action."""

    action_id: str
    approved: bool
    executed: bool
    command_result: CommandResult | None = None
    error: str = ""


@dataclass
class _PendingAction:
    """Internal state for an action awaiting approval."""

    action_id: str
    command: list[str]
    risk: ToolRisk
    description: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool = False
    approved_by: str = ""


class ActionEngine:
    """Orchestrates the approve → execute → audit flow for actions."""

    def __init__(
        self,
        sandbox: CommandSandbox | None = None,
        audit: AuditLogger | None = None,
        ws_manager: Any = None,
    ) -> None:
        self._sandbox = sandbox or CommandSandbox()
        self._audit = audit or AuditLogger()
        self._ws_manager = ws_manager
        self._pending: dict[str, _PendingAction] = {}

    async def propose_action(
        self,
        command: list[str],
        description: str = "",
        reason: str = "",
    ) -> ActionResult:
        """Propose an action. Auto-approves READ_ONLY, else waits for user."""
        action_id = str(uuid.uuid4())

        # Validate and get risk level
        allowed, risk = self._sandbox.validate_command(command)
        if not allowed:
            await self._audit.log_action(
                action=description or " ".join(command),
                command=" ".join(command),
                result="blocked by sandbox",
                success=False,
            )
            return ActionResult(
                action_id=action_id,
                approved=False,
                executed=False,
                error="Command blocked by safety filter",
            )

        # Auto-approve READ_ONLY
        if risk == ToolRisk.READ_ONLY:
            return await self._execute_action(action_id, command, description, auto=True)

        # Require user approval for everything else
        pending = _PendingAction(
            action_id=action_id,
            command=command,
            risk=risk,
            description=description,
        )
        self._pending[action_id] = pending

        # Broadcast ACTION_REQUEST via WebSocket
        if self._ws_manager:
            from argus_agent.api.protocol import ActionRequest

            req = ActionRequest(
                id=action_id,
                tool="run_command",
                description=description or f"Execute: {' '.join(command)}",
                command=command,
                risk_level=str(risk),
                reversible=False,
            )
            await self._ws_manager.broadcast(
                ServerMessage(
                    type=ServerMessageType.ACTION_REQUEST,
                    data=req.model_dump(),
                )
            )

        # Wait for approval
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=APPROVAL_TIMEOUT)
        except TimeoutError:
            self._pending.pop(action_id, None)
            await self._audit.log_action(
                action=description,
                command=" ".join(command),
                result="approval timed out",
                success=False,
            )
            return ActionResult(
                action_id=action_id,
                approved=False,
                executed=False,
                error="Approval timed out",
            )

        self._pending.pop(action_id, None)

        if not pending.approved:
            await self._audit.log_action(
                action=description,
                command=" ".join(command),
                result="rejected by user",
                success=False,
                user_approved=False,
            )
            return ActionResult(
                action_id=action_id,
                approved=False,
                executed=False,
                error="Action rejected by user",
            )

        return await self._execute_action(
            action_id, command, description, approved_by=pending.approved_by
        )

    async def _execute_action(
        self,
        action_id: str,
        command: list[str],
        description: str,
        auto: bool = False,
        approved_by: str = "",
    ) -> ActionResult:
        """Execute an approved action."""
        # Notify execution started
        if self._ws_manager:
            await self._ws_manager.broadcast(
                ServerMessage(
                    type=ServerMessageType.ACTION_EXECUTING,
                    data={"id": action_id, "command": command},
                )
            )

        cmd_result = await self._sandbox.execute(command)

        # Audit
        await self._audit.log_action(
            action=description or " ".join(command),
            command=" ".join(command),
            result=(
                cmd_result.stdout[:500] if cmd_result.exit_code == 0
                else cmd_result.stderr[:500]
            ),
            success=cmd_result.exit_code == 0,
            user_approved=not auto,
        )

        # Notify completion
        if self._ws_manager:
            await self._ws_manager.broadcast(
                ServerMessage(
                    type=ServerMessageType.ACTION_COMPLETE,
                    data={
                        "id": action_id,
                        "exit_code": cmd_result.exit_code,
                        "stdout": cmd_result.stdout[:1000],
                        "stderr": cmd_result.stderr[:1000],
                        "duration_ms": cmd_result.duration_ms,
                    },
                )
            )

        return ActionResult(
            action_id=action_id,
            approved=True,
            executed=True,
            command_result=cmd_result,
        )

    def handle_response(self, action_id: str, approved: bool, user: str = "") -> bool:
        """Handle an ACTION_RESPONSE from the WebSocket client.

        Returns True if the action was found and updated.
        """
        pending = self._pending.get(action_id)
        if pending is None:
            logger.warning("Action response for unknown action: %s", action_id)
            return False

        pending.approved = approved
        pending.approved_by = user
        pending.event.set()
        return True
