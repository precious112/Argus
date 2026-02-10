"""Tests for built-in actions."""

from __future__ import annotations

from argus_agent.actions.builtin import (
    BUILTIN_ACTIONS,
    BuiltinAction,
    clear_old_files,
    kill_process,
    restart_service,
    run_diagnostic,
)
from argus_agent.tools.base import ToolRisk


class TestBuiltinActions:
    def test_restart_service(self):
        cmd = restart_service("nginx")
        assert cmd == ["systemctl", "restart", "nginx"]

    def test_kill_process_default_signal(self):
        cmd = kill_process(1234)
        assert cmd == ["kill", "-15", "1234"]

    def test_kill_process_custom_signal(self):
        cmd = kill_process(1234, signal=9)
        assert cmd == ["kill", "-9", "1234"]

    def test_clear_old_files(self):
        cmd = clear_old_files("/tmp/logs", days=7)
        assert cmd == ["find", "/tmp/logs", "-type", "f", "-mtime", "+7", "-delete"]

    def test_run_diagnostic_known(self):
        cmd = run_diagnostic("disk_usage")
        assert cmd == ["df", "-h"]

    def test_run_diagnostic_unknown(self):
        cmd = run_diagnostic("unknown_check")
        assert cmd[0] == "echo"
        assert "Unknown" in cmd[1]

    def test_builtin_registry_has_entries(self):
        assert len(BUILTIN_ACTIONS) >= 5

    def test_builtin_action_dataclass(self):
        action = BUILTIN_ACTIONS["restart_service"]
        assert isinstance(action, BuiltinAction)
        assert action.risk == ToolRisk.MEDIUM
        assert action.reversible is True

    def test_kill_process_action_not_reversible(self):
        action = BUILTIN_ACTIONS["kill_process"]
        assert action.reversible is False
        assert action.risk == ToolRisk.HIGH

    def test_diagnostic_actions_are_read_only(self):
        for name in ["disk_usage", "memory_info", "network_check", "service_status"]:
            assert BUILTIN_ACTIONS[name].risk == ToolRisk.READ_ONLY
