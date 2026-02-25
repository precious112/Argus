"""Tests for command sandbox."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from argus_agent.actions.sandbox import DEFAULT_RISK, RISK_PATTERNS, _BLOCKLIST_PATTERNS, _is_blocked, CommandResult, CommandSandbox
from argus_agent.tools.base import ToolRisk


class TestCommandSandbox:
    def setup_method(self):
        self.sandbox = CommandSandbox()

    # -- Blocklist tests --

    def test_blocklist_rm_rf_root(self):
        allowed, risk = self.sandbox.validate_command(["rm", "-rf", "/"])
        assert allowed is False
        assert risk == ToolRisk.CRITICAL

    def test_blocklist_rm_rf_star(self):
        allowed, risk = self.sandbox.validate_command(["rm", "-rf", "/*"])
        assert allowed is False
        assert risk == ToolRisk.CRITICAL

    def test_blocklist_mkfs(self):
        allowed, risk = self.sandbox.validate_command(["mkfs.ext4", "/dev/sda1"])
        assert allowed is False
        assert risk == ToolRisk.CRITICAL

    def test_blocklist_dd(self):
        allowed, risk = self.sandbox.validate_command(["dd", "if=/dev/zero", "of=/dev/sda"])
        assert allowed is False
        assert risk == ToolRisk.CRITICAL

    def test_blocklist_iptables_flush(self):
        allowed, risk = self.sandbox.validate_command(["iptables", "-F"])
        assert allowed is False
        assert risk == ToolRisk.CRITICAL

    # -- Risk classification tests --

    def test_read_only_df(self):
        allowed, risk = self.sandbox.validate_command(["df", "-h"])
        assert allowed is True
        assert risk == ToolRisk.READ_ONLY

    def test_read_only_docker_stats(self):
        allowed, risk = self.sandbox.validate_command(["docker", "stats", "--no-stream"])
        assert allowed is True
        assert risk == ToolRisk.READ_ONLY

    def test_read_only_docker_ps(self):
        allowed, risk = self.sandbox.validate_command(["docker", "ps"])
        assert allowed is True
        assert risk == ToolRisk.READ_ONLY

    def test_read_only_docker_images(self):
        allowed, risk = self.sandbox.validate_command(["docker", "images"])
        assert allowed is True
        assert risk == ToolRisk.READ_ONLY

    def test_read_only_systemctl_status(self):
        allowed, risk = self.sandbox.validate_command(["systemctl", "status", "nginx"])
        assert allowed is True
        assert risk == ToolRisk.READ_ONLY

    def test_high_risk_kill(self):
        allowed, risk = self.sandbox.validate_command(["kill", "-9", "12345"])
        assert allowed is True
        assert risk == ToolRisk.HIGH

    def test_critical_risk_rm_rf(self):
        # rm -rf on a specific path (not / or /*) is allowed but CRITICAL
        allowed, risk = self.sandbox.validate_command(["rm", "-rf", "/tmp/junk"])
        assert allowed is True
        assert risk == ToolRisk.CRITICAL

    def test_critical_risk_reboot(self):
        allowed, risk = self.sandbox.validate_command(["reboot"])
        assert allowed is True
        assert risk == ToolRisk.CRITICAL

    # -- Default risk for unknown commands --

    def test_unknown_command_allowed_with_default_risk(self):
        """Commands not in blocklist or risk patterns get default risk (MEDIUM)."""
        allowed, risk = self.sandbox.validate_command(["htop"])
        assert allowed is True
        assert risk == DEFAULT_RISK

    def test_wget_allowed_with_default_risk(self):
        allowed, risk = self.sandbox.validate_command(["wget", "http://example.com"])
        assert allowed is True
        assert risk == DEFAULT_RISK

    def test_apt_allowed_with_default_risk(self):
        allowed, risk = self.sandbox.validate_command(["apt", "list", "--installed"])
        assert allowed is True
        assert risk == DEFAULT_RISK

    def test_docker_exec_allowed_with_default_risk(self):
        allowed, risk = self.sandbox.validate_command(["docker", "exec", "mycontainer", "ls"])
        assert allowed is True
        assert risk == DEFAULT_RISK

    # -- Blocklist edge cases --

    def test_rm_rf_system_path_blocked(self):
        """rm -rf targeting /usr should be blocked."""
        allowed, risk = self.sandbox.validate_command(["rm", "-rf", "/usr"])
        assert allowed is False

    def test_rm_with_trailing_slash_blocked(self):
        """rm -rf / with trailing slash variation."""
        assert _is_blocked("rm -rf /") is True

    def test_rm_user_path_not_blocked(self):
        """rm -rf on a user path like /tmp/junk should NOT be blocked."""
        allowed, risk = self.sandbox.validate_command(["rm", "-rf", "/tmp/junk"])
        assert allowed is True
        assert risk == ToolRisk.CRITICAL

    def test_custom_risk_patterns(self):
        sandbox = CommandSandbox(risk_patterns={"my-tool *": ToolRisk.LOW})
        allowed, risk = sandbox.validate_command(["my-tool", "arg1"])
        assert allowed is True
        assert risk == ToolRisk.LOW

    # -- Execution tests --

    @pytest.mark.asyncio
    async def test_execute_blocked_command(self):
        result = await self.sandbox.execute(["rm", "-rf", "/"])
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
    async def test_execute_unknown_command(self):
        """Unknown commands (not blocklisted) should execute successfully."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"data", b""))
        mock_proc.returncode = 0
        mock_proc.kill = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await self.sandbox.execute(["htop", "-n", "1"])
            assert result.exit_code == 0
            assert result.stdout == "data"

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

    def test_blocklist_has_entries(self):
        assert len(_BLOCKLIST_PATTERNS) > 5

    def test_risk_patterns_has_entries(self):
        assert len(RISK_PATTERNS) > 10

    def test_command_result_dataclass(self):
        r = CommandResult(exit_code=0, stdout="ok", stderr="", duration_ms=100)
        assert r.exit_code == 0
        assert r.duration_ms == 100
