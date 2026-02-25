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


# Paths that rm -rf / rm -r should never target
_PROTECTED_PATHS = frozenset({
    "/", "/*",
    "/etc", "/usr", "/var", "/boot", "/bin", "/sbin",
    "/lib", "/lib64", "/home", "/root", "/proc", "/sys", "/dev",
})

# Glob patterns for commands that are NEVER allowed
_BLOCKLIST_PATTERNS: list[str] = [
    # Disk/partition destruction
    "mkfs*",
    "dd if=*",
    "fdisk*",
    "parted*",
    "> /dev/sd*",
    "> /dev/nvm*",
    # Permission nuking
    "chmod -R 777 /",
    "chmod 777 /",
    # Network/firewall destruction
    "iptables -F",
    "iptables --flush",
    "nft flush ruleset",
    "ufw disable",
    # Fork bombs and resource exhaustion
    ":(){ :|:& };:*",
    # Kernel manipulation
    "sysctl -w*",
    "modprobe -r*",
    "rmmod*",
    "insmod*",
    # Bootloader destruction
    "grub-install*",
    "update-grub*",
]


def _is_blocked(cmd_str: str) -> bool:
    """Return True if the command is blocked."""
    # Check rm targeting protected paths
    parts = cmd_str.split()
    if len(parts) >= 2 and parts[0] == "rm":
        # Extract the target path (last argument after flags)
        targets = [p for p in parts[1:] if not p.startswith("-")]
        for target in targets:
            # Normalise trailing slashes for comparison
            normalised = target.rstrip("/") or "/"
            if normalised in _PROTECTED_PATHS or target in _PROTECTED_PATHS:
                return True

    # Check glob patterns
    for pattern in _BLOCKLIST_PATTERNS:
        if fnmatch(cmd_str, pattern):
            return True

    return False

# Risk classification: glob pattern → risk level.
# Commands matching these patterns get the specified risk level.
# Commands not matching any pattern default to MEDIUM (requires user approval).
RISK_PATTERNS: dict[str, ToolRisk] = {
    # READ_ONLY — auto-approved, no user interaction needed
    "df *": ToolRisk.READ_ONLY,
    "free *": ToolRisk.READ_ONLY,
    "uptime": ToolRisk.READ_ONLY,
    "uptime *": ToolRisk.READ_ONLY,
    "ps *": ToolRisk.READ_ONLY,
    "top -b -n 1*": ToolRisk.READ_ONLY,
    "cat /proc/*": ToolRisk.READ_ONLY,
    "cat /etc/*": ToolRisk.READ_ONLY,
    "cat /sys/*": ToolRisk.READ_ONLY,
    "ls *": ToolRisk.READ_ONLY,
    "ls": ToolRisk.READ_ONLY,
    "stat *": ToolRisk.READ_ONLY,
    "file *": ToolRisk.READ_ONLY,
    "wc *": ToolRisk.READ_ONLY,
    "head *": ToolRisk.READ_ONLY,
    "tail *": ToolRisk.READ_ONLY,
    "du *": ToolRisk.READ_ONLY,
    "lsblk*": ToolRisk.READ_ONLY,
    "lscpu*": ToolRisk.READ_ONLY,
    "lsmem*": ToolRisk.READ_ONLY,
    "lspci*": ToolRisk.READ_ONLY,
    "lsusb*": ToolRisk.READ_ONLY,
    "lsof *": ToolRisk.READ_ONLY,
    "mount": ToolRisk.READ_ONLY,
    "findmnt*": ToolRisk.READ_ONLY,
    "netstat *": ToolRisk.READ_ONLY,
    "ss *": ToolRisk.READ_ONLY,
    "ip *": ToolRisk.READ_ONLY,
    "ifconfig*": ToolRisk.READ_ONLY,
    "dig *": ToolRisk.READ_ONLY,
    "nslookup *": ToolRisk.READ_ONLY,
    "ping -c *": ToolRisk.READ_ONLY,
    "traceroute *": ToolRisk.READ_ONLY,
    "curl *": ToolRisk.READ_ONLY,
    "wget -q -O - *": ToolRisk.READ_ONLY,
    "journalctl *": ToolRisk.READ_ONLY,
    "dmesg*": ToolRisk.READ_ONLY,
    "systemctl status *": ToolRisk.READ_ONLY,
    "systemctl is-active *": ToolRisk.READ_ONLY,
    "systemctl is-enabled *": ToolRisk.READ_ONLY,
    "systemctl list-units*": ToolRisk.READ_ONLY,
    "systemctl list-timers*": ToolRisk.READ_ONLY,
    "docker ps*": ToolRisk.READ_ONLY,
    "docker logs *": ToolRisk.READ_ONLY,
    "docker stats *": ToolRisk.READ_ONLY,
    "docker images*": ToolRisk.READ_ONLY,
    "docker info*": ToolRisk.READ_ONLY,
    "docker inspect *": ToolRisk.READ_ONLY,
    "docker top *": ToolRisk.READ_ONLY,
    "docker volume ls*": ToolRisk.READ_ONLY,
    "docker network ls*": ToolRisk.READ_ONLY,
    "docker compose ps*": ToolRisk.READ_ONLY,
    "docker-compose ps*": ToolRisk.READ_ONLY,
    "hostname*": ToolRisk.READ_ONLY,
    "uname *": ToolRisk.READ_ONLY,
    "whoami": ToolRisk.READ_ONLY,
    "id": ToolRisk.READ_ONLY,
    "id *": ToolRisk.READ_ONLY,
    "date*": ToolRisk.READ_ONLY,
    "timedatectl*": ToolRisk.READ_ONLY,
    "cat *": ToolRisk.READ_ONLY,
    "grep *": ToolRisk.READ_ONLY,
    "awk *": ToolRisk.READ_ONLY,
    "sed -n *": ToolRisk.READ_ONLY,
    "find *": ToolRisk.READ_ONLY,
    "which *": ToolRisk.READ_ONLY,
    "type *": ToolRisk.READ_ONLY,
    "env": ToolRisk.READ_ONLY,
    "printenv*": ToolRisk.READ_ONLY,
    # HIGH risk — requires approval, flagged prominently
    "kill *": ToolRisk.HIGH,
    "pkill *": ToolRisk.HIGH,
    "killall *": ToolRisk.HIGH,
    "find * -delete": ToolRisk.HIGH,
    "find * -exec rm *": ToolRisk.HIGH,
    # CRITICAL risk — requires approval, strong warning
    "rm -rf *": ToolRisk.CRITICAL,
    "rm -r *": ToolRisk.CRITICAL,
    "reboot": ToolRisk.CRITICAL,
    "shutdown *": ToolRisk.CRITICAL,
    "poweroff": ToolRisk.CRITICAL,
    "init 0": ToolRisk.CRITICAL,
    "init 6": ToolRisk.CRITICAL,
}

# Default risk for commands not matching any pattern (requires user approval)
DEFAULT_RISK = ToolRisk.MEDIUM


class CommandSandbox:
    """Execute commands safely with blocklist validation.

    Uses a blocklist-only approach: any command not in the blocklist is
    allowed through, but non-READ_ONLY commands still require user
    approval via the action engine before execution.
    """

    def __init__(
        self,
        risk_patterns: dict[str, ToolRisk] | None = None,
    ) -> None:
        self._risk_patterns = risk_patterns if risk_patterns is not None else RISK_PATTERNS

    def validate_command(self, cmd: list[str]) -> tuple[bool, ToolRisk]:
        """Check if a command is allowed and return its risk level.

        Returns (allowed, risk_level). Blocked commands return (False, CRITICAL).
        Allowed commands return (True, <risk_level>) where the risk level is
        determined by matching RISK_PATTERNS, defaulting to MEDIUM.
        """
        cmd_str = " ".join(cmd)

        # Check blocklist — these are never allowed
        if _is_blocked(cmd_str):
            logger.warning("Blocked command (blocklist): %s", cmd_str)
            return False, ToolRisk.CRITICAL

        # Classify risk level from known patterns
        for pattern, risk in self._risk_patterns.items():
            if fnmatch(cmd_str, pattern):
                return True, risk

        # Not in blocklist, not in known patterns → allow with default risk
        logger.info("Command allowed with default risk (%s): %s", DEFAULT_RISK, cmd_str)
        return True, DEFAULT_RISK

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
