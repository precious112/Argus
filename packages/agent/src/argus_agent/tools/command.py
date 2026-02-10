"""Execute approved commands tool."""

from __future__ import annotations

import logging
from typing import Any

from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.command")


class RunCommandTool(Tool):
    """Execute a system command through the action engine with approval flow."""

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return (
            "Execute a system command. Safe commands (like df, free, ps) run automatically. "
            "Risky commands (restart, kill, delete) require user approval via the UI. "
            "Provide the command as an array of strings."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.HIGH

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command as array, e.g. ['systemctl', 'restart', 'nginx']",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this command should be run",
                },
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        command = kwargs.get("command", [])
        reason = kwargs.get("reason", "")

        if not command:
            return {"error": "No command provided"}

        # Get action engine from main
        from argus_agent.main import _get_action_engine

        engine = _get_action_engine()
        if engine is None:
            return {"error": "Action engine not initialized"}

        result = await engine.propose_action(
            command=command,
            description=reason or f"Execute: {' '.join(command)}",
        )

        if not result.approved:
            return {
                "status": "rejected",
                "reason": result.error,
                "display_type": "text",
            }

        if result.command_result is None:
            return {"status": "error", "error": "No result", "display_type": "text"}

        return {
            "status": "executed",
            "exit_code": result.command_result.exit_code,
            "stdout": result.command_result.stdout,
            "stderr": result.command_result.stderr,
            "duration_ms": result.command_result.duration_ms,
            "display_type": "code_block",
        }


def register_command_tools() -> None:
    """Register command tools."""
    from argus_agent.tools.base import register_tool

    register_tool(RunCommandTool())
