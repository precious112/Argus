"""Tests for action engine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.actions.engine import ActionEngine
from argus_agent.actions.sandbox import CommandResult, CommandSandbox
from argus_agent.tools.base import ToolRisk


class TestActionEngine:
    def setup_method(self):
        self.mock_sandbox = MagicMock(spec=CommandSandbox)
        self.mock_audit = AsyncMock()
        self.mock_audit.log_action = AsyncMock(return_value=1)
        self.mock_ws = AsyncMock()
        self.mock_ws.broadcast = AsyncMock()
        self.engine = ActionEngine(
            sandbox=self.mock_sandbox,
            audit=self.mock_audit,
            ws_manager=self.mock_ws,
        )

    @pytest.mark.asyncio
    async def test_blocked_command(self):
        self.mock_sandbox.validate_command.return_value = (False, ToolRisk.CRITICAL)
        result = await self.engine.propose_action(["rm", "-rf", "/"])
        assert result.approved is False
        assert result.executed is False
        assert "not in allowlist" in result.error

    @pytest.mark.asyncio
    async def test_auto_approve_read_only(self):
        self.mock_sandbox.validate_command.return_value = (True, ToolRisk.READ_ONLY)
        self.mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(exit_code=0, stdout="ok", stderr="", duration_ms=10)
        )
        result = await self.engine.propose_action(["df", "-h"])
        assert result.approved is True
        assert result.executed is True
        assert result.command_result is not None
        assert result.command_result.exit_code == 0

    @pytest.mark.asyncio
    async def test_approval_flow_approved(self):
        self.mock_sandbox.validate_command.return_value = (True, ToolRisk.HIGH)
        self.mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(exit_code=0, stdout="killed", stderr="", duration_ms=5)
        )

        async def approve_after_delay():
            await asyncio.sleep(0.05)
            # Find the pending action and approve it
            for action_id in list(self.engine._pending.keys()):
                self.engine.handle_response(action_id, approved=True, user="admin")

        task = asyncio.create_task(approve_after_delay())
        result = await self.engine.propose_action(["kill", "-9", "1234"])
        await task

        assert result.approved is True
        assert result.executed is True

    @pytest.mark.asyncio
    async def test_approval_flow_rejected(self):
        self.mock_sandbox.validate_command.return_value = (True, ToolRisk.HIGH)

        async def reject_after_delay():
            await asyncio.sleep(0.05)
            for action_id in list(self.engine._pending.keys()):
                self.engine.handle_response(action_id, approved=False, user="admin")

        task = asyncio.create_task(reject_after_delay())
        result = await self.engine.propose_action(["kill", "-9", "1234"])
        await task

        assert result.approved is False
        assert result.executed is False
        assert "rejected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_approval_timeout(self):
        self.mock_sandbox.validate_command.return_value = (True, ToolRisk.HIGH)

        # Patch APPROVAL_TIMEOUT to be very short
        with patch("argus_agent.actions.engine.APPROVAL_TIMEOUT", 0.05):
            result = await self.engine.propose_action(["kill", "-9", "1234"])

        assert result.approved is False
        assert "timed out" in result.error.lower()

    def test_handle_response_unknown_action(self):
        found = self.engine.handle_response("unknown-id", approved=True)
        assert found is False

    @pytest.mark.asyncio
    async def test_audit_called_on_execution(self):
        self.mock_sandbox.validate_command.return_value = (True, ToolRisk.READ_ONLY)
        self.mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(exit_code=0, stdout="ok", stderr="", duration_ms=10)
        )
        await self.engine.propose_action(["df", "-h"], description="Check disk")
        self.mock_audit.log_action.assert_called()

    @pytest.mark.asyncio
    async def test_ws_broadcast_on_action_request(self):
        self.mock_sandbox.validate_command.return_value = (True, ToolRisk.HIGH)

        # Will timeout quickly
        with patch("argus_agent.actions.engine.APPROVAL_TIMEOUT", 0.05):
            await self.engine.propose_action(["kill", "1234"])

        # Should have broadcast an ACTION_REQUEST
        self.mock_ws.broadcast.assert_called()

    @pytest.mark.asyncio
    async def test_ws_broadcast_on_completion(self):
        self.mock_sandbox.validate_command.return_value = (True, ToolRisk.READ_ONLY)
        self.mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(exit_code=0, stdout="ok", stderr="", duration_ms=10)
        )
        await self.engine.propose_action(["df", "-h"])
        # Should broadcast ACTION_EXECUTING and ACTION_COMPLETE
        assert self.mock_ws.broadcast.call_count >= 2

    @pytest.mark.asyncio
    async def test_engine_no_ws_manager(self):
        engine = ActionEngine(sandbox=self.mock_sandbox, audit=self.mock_audit, ws_manager=None)
        self.mock_sandbox.validate_command.return_value = (True, ToolRisk.READ_ONLY)
        self.mock_sandbox.execute = AsyncMock(
            return_value=CommandResult(exit_code=0, stdout="ok", stderr="", duration_ms=10)
        )
        result = await engine.propose_action(["df", "-h"])
        assert result.approved is True
