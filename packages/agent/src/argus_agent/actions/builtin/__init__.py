"""Built-in action templates for common operations."""

from __future__ import annotations

from dataclasses import dataclass

from argus_agent.tools.base import ToolRisk


@dataclass
class BuiltinAction:
    """A predefined action with a command template."""

    name: str
    description: str
    command_template: list[str]
    risk: ToolRisk
    reversible: bool = False


def restart_service(name: str) -> list[str]:
    """Generate command to restart a systemd service."""
    return ["systemctl", "restart", name]


def kill_process(pid: int, signal: int = 15) -> list[str]:
    """Generate command to kill a process by PID."""
    return ["kill", f"-{signal}", str(pid)]


def clear_old_files(path: str, days: int = 30) -> list[str]:
    """Generate command to find and delete files older than N days."""
    return ["find", path, "-type", "f", "-mtime", f"+{days}", "-delete"]


def run_diagnostic(check_name: str) -> list[str]:
    """Generate command for a named diagnostic check."""
    checks: dict[str, list[str]] = {
        "disk_usage": ["df", "-h"],
        "memory_info": ["free", "-h"],
        "network_check": ["ss", "-tulnp"],
        "service_status": ["systemctl", "list-units", "--failed"],
        "uptime": ["uptime"],
        "top_processes": ["ps", "aux", "--sort=-pcpu"],
        "io_stats": ["cat", "/proc/diskstats"],
    }
    return checks.get(check_name, ["echo", f"Unknown check: {check_name}"])


# Registry of all built-in actions
BUILTIN_ACTIONS: dict[str, BuiltinAction] = {
    "restart_service": BuiltinAction(
        name="restart_service",
        description="Restart a systemd service",
        command_template=["systemctl", "restart", "{name}"],
        risk=ToolRisk.MEDIUM,
        reversible=True,
    ),
    "kill_process": BuiltinAction(
        name="kill_process",
        description="Terminate a process by PID",
        command_template=["kill", "-{signal}", "{pid}"],
        risk=ToolRisk.HIGH,
        reversible=False,
    ),
    "clear_old_files": BuiltinAction(
        name="clear_old_files",
        description="Delete files older than N days in a directory",
        command_template=["find", "{path}", "-type", "f", "-mtime", "+{days}", "-delete"],
        risk=ToolRisk.HIGH,
        reversible=False,
    ),
    "disk_usage": BuiltinAction(
        name="disk_usage",
        description="Check disk usage",
        command_template=["df", "-h"],
        risk=ToolRisk.READ_ONLY,
        reversible=True,
    ),
    "memory_info": BuiltinAction(
        name="memory_info",
        description="Check memory usage",
        command_template=["free", "-h"],
        risk=ToolRisk.READ_ONLY,
        reversible=True,
    ),
    "network_check": BuiltinAction(
        name="network_check",
        description="Check network connections",
        command_template=["ss", "-tulnp"],
        risk=ToolRisk.READ_ONLY,
        reversible=True,
    ),
    "service_status": BuiltinAction(
        name="service_status",
        description="Check for failed services",
        command_template=["systemctl", "list-units", "--failed"],
        risk=ToolRisk.READ_ONLY,
        reversible=True,
    ),
}
