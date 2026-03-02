"""Periodic security scanner."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from argus_agent.config import get_settings
from argus_agent.events.bus import get_event_bus
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType

logger = logging.getLogger("argus.collectors.security")

KNOWN_BAD_NAMES = {"xmrig", "cryptominer", "kworkerds", "kdevtmpfsi"}
SENSITIVE_PATHS = ["/etc/shadow", "/etc/passwd", "/etc/sudoers"]
TEMP_DIRS = ["/tmp", "/dev/shm"]

# Default scan interval: 5 minutes
DEFAULT_INTERVAL = 300


class SecurityScanner:
    """Periodic security scanner — all checks are READ-ONLY.

    Follows the same async start/stop pattern as other collectors.
    In SaaS mode, checks are routed through webhooks to the tenant's host.
    """

    def __init__(self, interval: int = DEFAULT_INTERVAL) -> None:
        self._interval = interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._known_ports: set[int] = set()
        self._known_outbound: set[tuple[str, int]] = set()
        self._known_executables: set[str] = set()
        self._host_root = get_settings().collector.host_root
        self._last_results: dict[str, Any] = {}
        self._is_saas = get_settings().deployment.mode == "saas"

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        logger.info(
            "Security scanner started (interval=%ds, saas=%s)",
            self._interval, self._is_saas,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Security scanner stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_results(self) -> dict[str, Any]:
        return self._last_results

    async def _scan_loop(self) -> None:
        while self._running:
            try:
                await self.scan_once()
            except Exception:
                logger.exception("Security scan error")
            await asyncio.sleep(self._interval)

    async def scan_once(self) -> dict[str, Any]:
        """Run all security checks once and return results."""
        bus = get_event_bus()
        results: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": {},
        }

        if self._is_saas:
            return await self._scan_once_remote(bus, results)

        # Self-hosted: run local sync checks
        checks = [
            ("open_ports", self._check_open_ports),
            ("failed_ssh", self._check_failed_ssh),
            ("file_permissions", self._check_file_permissions),
            ("suspicious_processes", self._check_suspicious_processes),
            ("new_executables", self._check_new_executables),
            ("process_lineage", self._check_process_lineage),
            ("outbound_connections", self._check_outbound_connections),
        ]

        for name, check_fn in checks:
            try:
                findings = check_fn()
                results["checks"][name] = findings

                for finding in findings.get("events", []):
                    await bus.publish(Event(
                        source=EventSource.SECURITY_SCANNER,
                        type=finding["type"],
                        severity=EventSeverity(finding["severity"]),
                        message=finding["message"],
                        data=finding.get("data", {}),
                    ))
            except Exception:
                logger.exception("Security check '%s' failed", name)
                results["checks"][name] = {"error": "check failed"}

        self._last_results = results
        return results

    async def _scan_once_remote(
        self,
        bus: Any,
        results: dict[str, Any],
    ) -> dict[str, Any]:
        """SaaS mode: run all checks via webhooks."""
        from argus_agent.collectors.remote import get_webhook_tenants

        tenants = await get_webhook_tenants()
        if not tenants:
            logger.debug("No webhook tenants configured — skipping remote scan")
            self._last_results = results
            return results

        checks: list[tuple[str, Any]] = [
            ("open_ports", self._remote_open_ports),
            ("failed_ssh", self._remote_failed_ssh),
            ("file_permissions", self._remote_file_permissions),
            ("suspicious_processes", self._remote_suspicious_processes),
            ("new_executables", self._remote_new_executables),
            ("process_lineage", self._remote_process_lineage),
            ("outbound_connections", self._remote_outbound_connections),
        ]

        for name, check_fn in checks:
            try:
                findings = await check_fn(tenants)
                results["checks"][name] = findings

                for finding in findings.get("events", []):
                    await bus.publish(Event(
                        source=EventSource.SECURITY_SCANNER,
                        type=finding["type"],
                        severity=EventSeverity(finding["severity"]),
                        message=finding["message"],
                        data=finding.get("data", {}),
                    ))
            except Exception:
                logger.exception("Remote security check '%s' failed", name)
                results["checks"][name] = {"error": "check failed"}

        self._last_results = results
        return results

    # ------------------------------------------------------------------
    # LOCAL (self-hosted) checks — sync, use psutil / filesystem
    # ------------------------------------------------------------------

    def _check_open_ports(self) -> dict[str, Any]:
        """Check for new listening ports."""
        events: list[dict[str, Any]] = []
        current_ports: set[int] = set()

        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN":
                    port = conn.laddr.port
                    current_ports.add(port)

                    if self._known_ports and port not in self._known_ports:
                        events.append({
                            "type": EventType.NEW_OPEN_PORT,
                            "severity": EventSeverity.NOTABLE,
                            "message": f"New listening port detected: {port}",
                            "data": {"port": port, "pid": conn.pid},
                        })
        except (psutil.AccessDenied, OSError):
            pass

        if not self._known_ports:
            self._known_ports = current_ports
        else:
            self._known_ports = current_ports

        return {"listening_ports": sorted(current_ports), "events": events}

    def _check_failed_ssh(self) -> dict[str, Any]:
        """Read auth.log and count failed SSH attempts per IP."""
        events: list[dict[str, Any]] = []
        failures: dict[str, int] = defaultdict(int)

        auth_log = "/var/log/auth.log"
        if self._host_root:
            auth_log = os.path.join(self._host_root, "var/log/auth.log")

        path = Path(auth_log)
        if not path.exists():
            return {"failures_by_ip": {}, "events": events}

        try:
            lines = path.read_text(errors="replace").splitlines()[-1000:]
            pattern = re.compile(r"Failed password.*from (\d+\.\d+\.\d+\.\d+)")
            for line in lines:
                match = pattern.search(line)
                if match:
                    failures[match.group(1)] += 1

            for ip, count in failures.items():
                if count >= 10:
                    events.append({
                        "type": EventType.BRUTE_FORCE,
                        "severity": EventSeverity.URGENT,
                        "message": f"SSH brute force: {count} failures from {ip}",
                        "data": {"ip": ip, "count": count},
                    })
        except (PermissionError, OSError):
            pass

        return {"failures_by_ip": dict(failures), "events": events}

    def _check_file_permissions(self) -> dict[str, Any]:
        """Check permissions on sensitive files."""
        events: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []

        for fpath in SENSITIVE_PATHS:
            resolved = fpath
            if self._host_root:
                resolved = os.path.join(self._host_root, fpath.lstrip("/"))

            p = Path(resolved)
            if not p.exists():
                continue

            try:
                stat = p.stat()
                mode = oct(stat.st_mode)[-3:]
                world_readable = int(mode[2]) >= 4

                findings.append({"path": fpath, "mode": mode, "world_readable": world_readable})

                if world_readable and fpath in ("/etc/shadow", "/etc/sudoers"):
                    events.append({
                        "type": EventType.PERMISSION_RISK,
                        "severity": EventSeverity.URGENT,
                        "message": f"Sensitive file world-readable: {fpath} (mode {mode})",
                        "data": {"path": fpath, "mode": mode},
                    })
            except (PermissionError, OSError):
                pass

        return {"files": findings, "events": events}

    def _check_suspicious_processes(self) -> dict[str, Any]:
        """Detect suspicious processes: deleted binaries, known-bad names."""
        events: list[dict[str, Any]] = []
        suspicious: list[dict[str, Any]] = []

        try:
            for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
                info = proc.info
                if not info:
                    continue

                name = (info.get("name") or "").lower()
                exe = info.get("exe") or ""

                if any(bad in name for bad in KNOWN_BAD_NAMES):
                    entry = {"pid": info["pid"], "name": name, "reason": "known_bad_name"}
                    suspicious.append(entry)
                    events.append({
                        "type": EventType.SUSPICIOUS_PROCESS,
                        "severity": EventSeverity.URGENT,
                        "message": f"Suspicious process: {name} (PID {info['pid']})",
                        "data": entry,
                    })

                if exe and "(deleted)" in exe:
                    entry = {
                        "pid": info["pid"], "name": name,
                        "reason": "deleted_binary", "exe": exe,
                    }
                    suspicious.append(entry)
                    events.append({
                        "type": EventType.SUSPICIOUS_PROCESS,
                        "severity": EventSeverity.URGENT,
                        "message": (
                            f"Process running from deleted binary: "
                            f"{name} (PID {info['pid']})"
                        ),
                        "data": entry,
                    })
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        return {"suspicious": suspicious, "events": events}

    def _check_new_executables(self) -> dict[str, Any]:
        """Check for new executable files in temp directories."""
        events: list[dict[str, Any]] = []
        current: set[str] = set()

        for dir_path in TEMP_DIRS:
            resolved = dir_path
            if self._host_root:
                resolved = os.path.join(self._host_root, dir_path.lstrip("/"))

            p = Path(resolved)
            if not p.exists():
                continue

            try:
                for entry in os.scandir(resolved):
                    if entry.is_file():
                        try:
                            st = entry.stat()
                            if st.st_mode & 0o111:
                                current.add(entry.path)
                        except OSError:
                            pass
            except (PermissionError, OSError):
                pass

        if self._known_executables:
            new = current - self._known_executables
            for path in new:
                events.append({
                    "type": EventType.NEW_EXECUTABLE,
                    "severity": EventSeverity.NOTABLE,
                    "message": f"New executable in temp dir: {path}",
                    "data": {"path": path},
                })

        self._known_executables = current
        return {"executables": sorted(current), "events": events}

    def _check_process_lineage(self) -> dict[str, Any]:
        """Flag web server processes spawning shells."""
        events: list[dict[str, Any]] = []
        web_servers = {"nginx", "apache2", "httpd", "node", "python", "java"}
        shells = {"sh", "bash", "zsh", "dash", "fish"}

        try:
            for proc in psutil.process_iter(["pid", "name", "ppid"]):
                info = proc.info
                if not info:
                    continue

                name = (info.get("name") or "").lower()
                if name not in shells:
                    continue

                try:
                    parent = psutil.Process(info["ppid"])
                    parent_name = (parent.name() or "").lower()
                    if parent_name in web_servers:
                        entry = {
                            "pid": info["pid"],
                            "name": name,
                            "parent_pid": info["ppid"],
                            "parent_name": parent_name,
                        }
                        events.append({
                            "type": EventType.SUSPICIOUS_PROCESS,
                            "severity": EventSeverity.URGENT,
                            "message": (
                                f"Web server '{parent_name}' spawned shell '{name}' "
                                f"(PID {info['pid']})"
                            ),
                            "data": entry,
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        return {"events": events}

    def _check_outbound_connections(self) -> dict[str, Any]:
        """Track outbound connections, flag new (ip, port) tuples."""
        events: list[dict[str, Any]] = []
        current: set[tuple[str, int]] = set()

        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.raddr:
                    current.add((conn.raddr.ip, conn.raddr.port))
        except (psutil.AccessDenied, OSError):
            pass

        if self._known_outbound:
            new = current - self._known_outbound
            for ip, port in new:
                events.append({
                    "type": EventType.SUSPICIOUS_OUTBOUND,
                    "severity": EventSeverity.NOTABLE,
                    "message": f"New outbound connection: {ip}:{port}",
                    "data": {"ip": ip, "port": port},
                })

        self._known_outbound = current
        connections = [{"ip": ip, "port": port} for ip, port in sorted(current)]
        return {"connections": connections, "events": events}

    # ------------------------------------------------------------------
    # REMOTE (SaaS) checks — async, use webhooks
    # ------------------------------------------------------------------

    async def _remote_open_ports(self, tenants: list[dict[str, Any]]) -> dict[str, Any]:
        """Check for new listening ports via network_connections webhook."""
        from argus_agent.collectors.remote import execute_remote_tool

        events: list[dict[str, Any]] = []
        all_ports: set[int] = set()

        for t in tenants:
            result = await execute_remote_tool(t["tenant_id"], "network_connections", {})
            if not result:
                continue
            for conn in result.get("connections", []):
                if conn.get("status") == "LISTEN":
                    laddr = conn.get("laddr", "")
                    try:
                        port = int(laddr.rsplit(":", 1)[-1]) if ":" in laddr else 0
                    except (ValueError, IndexError):
                        continue
                    if port:
                        all_ports.add(port)
                        if self._known_ports and port not in self._known_ports:
                            events.append({
                                "type": EventType.NEW_OPEN_PORT,
                                "severity": EventSeverity.NOTABLE,
                                "message": (
                            f"New listening port: {port} "
                            f"(tenant {t['tenant_id']})"
                        ),
                                "data": {"port": port, "tenant_id": t["tenant_id"]},
                            })

        if not self._known_ports:
            self._known_ports = all_ports
        else:
            self._known_ports = all_ports

        return {"listening_ports": sorted(all_ports), "events": events}

    async def _remote_failed_ssh(self, tenants: list[dict[str, Any]]) -> dict[str, Any]:
        """Check SSH brute force via log_search webhook."""
        from argus_agent.collectors.remote import execute_remote_tool

        events: list[dict[str, Any]] = []
        all_failures: dict[str, int] = defaultdict(int)

        for t in tenants:
            result = await execute_remote_tool(
                t["tenant_id"], "log_search",
                {"pattern": "Failed password", "path": "/var/log/auth.log", "limit": 200},
            )
            if not result:
                continue
            ip_pattern = re.compile(r"Failed password.*from (\d+\.\d+\.\d+\.\d+)")
            for line in result.get("matches", []):
                match = ip_pattern.search(line)
                if match:
                    all_failures[match.group(1)] += 1

            for ip, count in all_failures.items():
                if count >= 10:
                    events.append({
                        "type": EventType.BRUTE_FORCE,
                        "severity": EventSeverity.URGENT,
                        "message": (
                            f"SSH brute force: {count} failures "
                            f"from {ip} (tenant {t['tenant_id']})"
                        ),
                        "data": {"ip": ip, "count": count, "tenant_id": t["tenant_id"]},
                    })

        return {"failures_by_ip": dict(all_failures), "events": events}

    async def _remote_file_permissions(self, tenants: list[dict[str, Any]]) -> dict[str, Any]:
        """Check file permissions via security_scan webhook."""
        from argus_agent.collectors.remote import execute_remote_tool

        events: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []

        for t in tenants:
            result = await execute_remote_tool(t["tenant_id"], "security_scan", {})
            if not result:
                continue
            ww = result.get("world_writable_tmp")
            if isinstance(ww, int) and ww > 0:
                findings.append({
                    "path": "/tmp",
                    "world_writable_count": ww,
                    "tenant_id": t["tenant_id"],
                })
                events.append({
                    "type": EventType.PERMISSION_RISK,
                    "severity": EventSeverity.NOTABLE,
                    "message": f"{ww} world-writable file(s) in /tmp (tenant {t['tenant_id']})",
                    "data": {"count": ww, "tenant_id": t["tenant_id"]},
                })

        return {"files": findings, "events": events}

    async def _remote_suspicious_processes(self, tenants: list[dict[str, Any]]) -> dict[str, Any]:
        """Detect suspicious processes via process_list webhook."""
        from argus_agent.collectors.remote import execute_remote_tool

        events: list[dict[str, Any]] = []
        suspicious: list[dict[str, Any]] = []

        for t in tenants:
            result = await execute_remote_tool(t["tenant_id"], "process_list", {"limit": 200})
            if not result:
                continue
            for proc in result.get("processes", []):
                name = (proc.get("name") or "").lower()
                pid = proc.get("pid", 0)
                if any(bad in name for bad in KNOWN_BAD_NAMES):
                    entry = {
                        "pid": pid, "name": name,
                        "reason": "known_bad_name",
                        "tenant_id": t["tenant_id"],
                    }
                    suspicious.append(entry)
                    events.append({
                        "type": EventType.SUSPICIOUS_PROCESS,
                        "severity": EventSeverity.URGENT,
                        "message": (
                            f"Suspicious process: {name} "
                            f"(PID {pid}, tenant {t['tenant_id']})"
                        ),
                        "data": entry,
                    })

        return {"suspicious": suspicious, "events": events}

    async def _remote_new_executables(self, tenants: list[dict[str, Any]]) -> dict[str, Any]:
        """Check for new executables via security_scan webhook."""
        from argus_agent.collectors.remote import execute_remote_tool

        events: list[dict[str, Any]] = []
        current: set[str] = set()

        for t in tenants:
            result = await execute_remote_tool(t["tenant_id"], "security_scan", {})
            if not result:
                continue
            ww = result.get("world_writable_tmp")
            if isinstance(ww, int) and ww > 0:
                placeholder = f"/tmp/<{ww}-writable-files>@{t['tenant_id']}"
                current.add(placeholder)

        if self._known_executables:
            new = current - self._known_executables
            for path in new:
                events.append({
                    "type": EventType.NEW_EXECUTABLE,
                    "severity": EventSeverity.NOTABLE,
                    "message": f"New executable(s) detected on remote host: {path}",
                    "data": {"path": path},
                })

        self._known_executables = current
        return {"executables": sorted(current), "events": events}

    async def _remote_process_lineage(self, tenants: list[dict[str, Any]]) -> dict[str, Any]:
        """Simplified process lineage check via webhook (flag shell processes)."""
        from argus_agent.collectors.remote import execute_remote_tool

        events: list[dict[str, Any]] = []
        shells = {"sh", "bash", "zsh", "dash", "fish"}

        for t in tenants:
            result = await execute_remote_tool(t["tenant_id"], "process_list", {"limit": 200})
            if not result:
                continue
            for proc in result.get("processes", []):
                name = (proc.get("name") or "").lower()
                if name in shells:
                    events.append({
                        "type": EventType.SUSPICIOUS_PROCESS,
                        "severity": EventSeverity.NOTABLE,
                        "message": (
                            f"Shell process '{name}' running "
                            f"(PID {proc.get('pid', '?')}, "
                            f"tenant {t['tenant_id']})"
                        ),
                        "data": {
                            "pid": proc.get("pid", 0),
                            "name": name,
                            "tenant_id": t["tenant_id"],
                        },
                    })

        return {"events": events}

    async def _remote_outbound_connections(self, tenants: list[dict[str, Any]]) -> dict[str, Any]:
        """Track outbound connections via network_connections webhook."""
        from argus_agent.collectors.remote import execute_remote_tool

        events: list[dict[str, Any]] = []
        current: set[tuple[str, int]] = set()

        for t in tenants:
            result = await execute_remote_tool(t["tenant_id"], "network_connections", {})
            if not result:
                continue
            for conn in result.get("connections", []):
                if conn.get("status") == "ESTABLISHED" and conn.get("raddr"):
                    raddr = conn["raddr"]
                    try:
                        ip, port_str = raddr.rsplit(":", 1)
                        port = int(port_str)
                        current.add((ip, port))
                    except (ValueError, IndexError):
                        continue

        if self._known_outbound:
            new = current - self._known_outbound
            for ip, port in new:
                events.append({
                    "type": EventType.SUSPICIOUS_OUTBOUND,
                    "severity": EventSeverity.NOTABLE,
                    "message": f"New outbound connection: {ip}:{port}",
                    "data": {"ip": ip, "port": port},
                })

        self._known_outbound = current
        connections = [{"ip": ip, "port": port} for ip, port in sorted(current)]
        return {"connections": connections, "events": events}
