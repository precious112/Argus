"""Tests for run_command tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from argus_agent.actions.engine import ActionResult
from argus_agent.actions.sandbox import CommandResult
from argus_agent.tools.command import RunCommandTool


class TestRunCommandTool:
    def setup_method(self):
        self.tool = RunCommandTool()

    def test_tool_properties(self):
        assert self.tool.name == "run_command"
        assert "command" in self.tool.parameters_schema["properties"]
        assert self.tool.risk.value == "HIGH"

    @pytest.mark.asyncio
    async def test_execute_no_command(self):
        result = await self.tool.execute()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_success(self):
        mock_engine = AsyncMock()
        mock_engine.propose_action = AsyncMock(
            return_value=ActionResult(
                action_id="test-id",
                approved=True,
                executed=True,
                command_result=CommandResult(
                    exit_code=0, stdout="output", stderr="", duration_ms=10
                ),
            )
        )
        with patch("argus_agent.main._get_action_engine", return_value=mock_engine):
            result = await self.tool.execute(command=["df", "-h"], reason="Check disk")
            assert result["status"] == "executed"
            assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_execute_rejected(self):
        mock_engine = AsyncMock()
        mock_engine.propose_action = AsyncMock(
            return_value=ActionResult(
                action_id="test-id",
                approved=False,
                executed=False,
                error="Action rejected by user",
            )
        )
        with patch("argus_agent.main._get_action_engine", return_value=mock_engine):
            result = await self.tool.execute(command=["kill", "-9", "1234"])
            assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_execute_engine_not_initialized(self):
        with patch("argus_agent.main._get_action_engine", return_value=None):
            result = await self.tool.execute(command=["df", "-h"])
            assert "error" in result
