"""Command sandboxing for safe action execution."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from fnmatch import fnmatch

from argus_agent.tools.base import ToolRisk

logger = logging.getLogger("argus.actions.sandbox")

# When running inside a container with host PID namespace, use nsenter to
# execute commands in the host's namespaces.  ARGUS_HOST_ROOT is set in
# docker-compose when host volumes are mounted.
_HOST_ROOT = os.environ.get("ARGUS_HOST_ROOT", "")
_NSENTER_PREFIX: list[str] = (
    ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "--"]
    if _HOST_ROOT
    else []
)


@dataclass
class CommandResult:
    """Result of a sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


# Allowlist: glob pattern → risk level
COMMAND_ALLOWLIST: dict[str, ToolRisk] = {
    # READ_ONLY diagnostics
    "df *": ToolRisk.READ_ONLY,
    "free *": ToolRisk.READ_ONLY,
    "uptime": ToolRisk.READ_ONLY,
    "ps *": ToolRisk.READ_ONLY,
    "top -b -n 1*": ToolRisk.READ_ONLY,
    "cat /proc/*": ToolRisk.READ_ONLY,
    "ls *": ToolRisk.READ_ONLY,
    "netstat *": ToolRisk.READ_ONLY,
    "ss *": ToolRisk.READ_ONLY,
    "ip *": ToolRisk.READ_ONLY,
    "dig *": ToolRisk.READ_ONLY,
    "nslookup *": ToolRisk.READ_ONLY,
    "ping -c *": ToolRisk.READ_ONLY,
    "curl *": ToolRisk.READ_ONLY,
    "journalctl *": ToolRisk.READ_ONLY,
    "systemctl status *": ToolRisk.READ_ONLY,
    "docker ps*": ToolRisk.READ_ONLY,
    "docker logs *": ToolRisk.READ_ONLY,
    # LOW risk
    "echo *": ToolRisk.LOW,
    # MEDIUM risk
    "systemctl restart *": ToolRisk.MEDIUM,
    "systemctl reload *": ToolRisk.MEDIUM,
    "docker restart *": ToolRisk.MEDIUM,
    "docker stop *": ToolRisk.MEDIUM,
    "docker start *": ToolRisk.MEDIUM,
    "service * restart": ToolRisk.MEDIUM,
    "service * reload": ToolRisk.MEDIUM,
    # HIGH risk
    "kill *": ToolRisk.HIGH,
    "kill -9 *": ToolRisk.HIGH,
    "kill -15 *": ToolRisk.HIGH,
    "pkill *": ToolRisk.HIGH,
    "find * -delete": ToolRisk.HIGH,
    "find * -exec rm *": ToolRisk.HIGH,
    # CRITICAL risk
    "rm -rf *": ToolRisk.CRITICAL,
    "rm -r *": ToolRisk.CRITICAL,
    "reboot": ToolRisk.CRITICAL,
    "shutdown *": ToolRisk.CRITICAL,
}

# Commands that are NEVER allowed regardless of allowlist
_BLOCKLIST = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs*",
    "dd if=*",
    "chmod -R 777 /",
    "> /dev/sd*",
]


class CommandSandbox:
    """Execute commands safely with allowlist validation."""

    def __init__(self, allowlist: dict[str, ToolRisk] | None = None) -> None:
        self._allowlist = allowlist or COMMAND_ALLOWLIST

    def validate_command(self, cmd: list[str]) -> tuple[bool, ToolRisk]:
        """Check if a command is allowed and return its risk level.

        Returns (allowed, risk_level). If not allowed, risk is CRITICAL.
        """
        cmd_str = " ".join(cmd)

        # Check blocklist first
        for pattern in _BLOCKLIST:
            if fnmatch(cmd_str, pattern):
                logger.warning("Blocked command (blocklist): %s", cmd_str)
                return False, ToolRisk.CRITICAL

        # Check allowlist
        for pattern, risk in self._allowlist.items():
            if fnmatch(cmd_str, pattern):
                return True, risk

        logger.warning("Command not in allowlist: %s", cmd_str)
        return False, ToolRisk.CRITICAL

    async def execute(
        self,
        cmd: list[str],
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """Execute a validated command via asyncio subprocess.

        Always uses exec (never shell=True). Enforces timeout.
        When running inside a container, commands are wrapped with nsenter
        to execute in the host's namespaces.
        """
        allowed, _risk = self.validate_command(cmd)
        if not allowed:
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command blocked: {' '.join(cmd)}",
                duration_ms=0,
            )

        exec_cmd = _NSENTER_PREFIX + cmd if _NSENTER_PREFIX else cmd

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            return CommandResult(
                exit_code=proc.returncode or 0,
                stdout=stdout_bytes.decode(errors="replace")[:10_000],
                stderr=stderr_bytes.decode(errors="replace")[:10_000],
                duration_ms=duration_ms,
            )
        except TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except ProcessLookupError:
                pass
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
            )
