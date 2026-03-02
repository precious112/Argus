"""Argus SDK webhook handler — receives tool execution requests from Argus cloud.

Usage with FastAPI::

    from argus.webhook import ArgusWebhookHandler

    handler = ArgusWebhookHandler(webhook_secret="your-secret")
    app.include_router(handler.fastapi_router())

Usage with Flask::

    handler = ArgusWebhookHandler(webhook_secret="your-secret")
    app.register_blueprint(handler.flask_blueprint())
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

logger = logging.getLogger("argus.webhook")


# ---------------------------------------------------------------------------
# HMAC verification (self-contained — no dependency on the agent package)
# ---------------------------------------------------------------------------

def _verify_signature(
    payload: bytes,
    secret: str,
    signature: str,
    timestamp: str,
    nonce: str,
    max_age: int = 300,
) -> bool:
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > max_age:
        return False
    message = f"{timestamp}.{nonce}.".encode() + payload
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


# ---------------------------------------------------------------------------
# Built-in host-level tool implementations
# ---------------------------------------------------------------------------

def _tool_system_metrics(**_kwargs: Any) -> dict[str, Any]:
    """Collect basic system metrics."""
    try:
        import psutil
    except ImportError:
        return {"error": "psutil not installed"}
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory": {
            "total_gb": round(mem.total / 1e9, 2),
            "used_gb": round(mem.used / 1e9, 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1e9, 2),
            "used_gb": round(disk.used / 1e9, 2),
            "percent": disk.percent,
        },
        "load_avg": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
    }


def _tool_process_list(**kwargs: Any) -> dict[str, Any]:
    """List running processes."""
    try:
        import psutil
    except ImportError:
        return {"error": "psutil not installed"}
    limit = int(kwargs.get("limit", 20))
    sort_by = kwargs.get("sort_by", "cpu")
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
    procs.sort(key=lambda x: x.get(key) or 0, reverse=True)
    return {"processes": procs[:limit], "total": len(procs)}


def _tool_network_connections(**kwargs: Any) -> dict[str, Any]:
    """List network connections and interfaces."""
    try:
        import psutil
    except ImportError:
        return {"error": "psutil not installed"}
    conns = []
    for c in psutil.net_connections(kind="inet"):
        conns.append({
            "fd": c.fd,
            "family": str(c.family),
            "type": str(c.type),
            "laddr": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
            "raddr": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "",
            "status": c.status,
            "pid": c.pid,
        })
    limit = int(kwargs.get("limit", 50))
    return {"connections": conns[:limit], "total": len(conns)}


def _tool_log_search(**kwargs: Any) -> dict[str, Any]:
    """Search log files for a pattern."""
    path = kwargs.get("path", "/var/log/syslog")
    pattern = kwargs.get("pattern", "")
    limit = int(kwargs.get("limit", 50))
    if not pattern:
        return {"error": "pattern is required"}
    try:
        result = subprocess.run(
            ["grep", "-n", "-i", pattern, path],
            capture_output=True, text=True, timeout=10,
        )
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
        return {"matches": lines[-limit:], "total": len(lines)}
    except subprocess.TimeoutExpired:
        return {"error": "Search timed out"}
    except Exception as e:
        return {"error": str(e)}


def _tool_security_scan(**_kwargs: Any) -> dict[str, Any]:
    """Basic security checks."""
    checks: dict[str, Any] = {}
    # Check for world-writable files in common dirs
    try:
        result = subprocess.run(
            ["find", "/tmp", "-maxdepth", "1", "-perm", "-o+w", "-type", "f"],
            capture_output=True, text=True, timeout=5,
        )
        checks["world_writable_tmp"] = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
    except Exception:
        checks["world_writable_tmp"] = "check_failed"
    # Check listening ports
    try:
        import psutil
        listeners = [
            {"port": c.laddr.port, "pid": c.pid}
            for c in psutil.net_connections(kind="inet")
            if c.status == "LISTEN"
        ]
        checks["listening_ports"] = listeners
    except Exception:
        checks["listening_ports"] = "check_failed"
    # Check disk encryption hint
    checks["hostname"] = socket.gethostname()
    return checks


def _tool_run_command(**kwargs: Any) -> dict[str, Any]:
    """Execute a shell command with a timeout."""
    command = kwargs.get("command", "")
    timeout = min(int(kwargs.get("timeout", 10)), 30)
    if not command:
        return {"error": "command is required"}
    # Basic safety check
    blocked = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd"]
    for b in blocked:
        if b in command:
            return {"error": f"Blocked dangerous command pattern: {b}"}
    try:
        result = subprocess.run(
            command, shell=True,
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "stdout": result.stdout[-4096:],
            "stderr": result.stderr[-2048:],
            "return_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}


_DEFAULT_TOOLS: dict[str, Any] = {
    "system_metrics": _tool_system_metrics,
    "process_list": _tool_process_list,
    "network_connections": _tool_network_connections,
    "log_search": _tool_log_search,
    "security_scan": _tool_security_scan,
    "run_command": _tool_run_command,
}


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

class ArgusWebhookHandler:
    """Receives tool execution requests from Argus cloud agent.

    Parameters
    ----------
    webhook_secret:
        Shared secret used for HMAC-SHA256 request verification.
    tools:
        Optional dict of ``{tool_name: callable}``.  Each callable
        receives ``**arguments`` and returns a JSON-serialisable dict.
        When omitted, the built-in host-level tools are used.
    """

    def __init__(
        self,
        webhook_secret: str,
        tools: Optional[dict[str, Any]] = None,
    ) -> None:
        self.secret = webhook_secret
        self.tools: dict[str, Any] = tools if tools is not None else dict(_DEFAULT_TOOLS)
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _verify(self, body: bytes, headers: dict[str, str]) -> bool:
        sig = headers.get("x-argus-signature", headers.get("X-Argus-Signature", ""))
        ts = headers.get("x-argus-timestamp", headers.get("X-Argus-Timestamp", ""))
        nonce = headers.get("x-argus-nonce", headers.get("X-Argus-Nonce", ""))
        return _verify_signature(body, self.secret, sig, ts, nonce)

    def handle_request_sync(self, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        """Verify signature and execute requested tool (sync)."""
        if not self._verify(body, headers):
            return {"error": "Invalid signature", "result": None}

        payload = json.loads(body)
        req_type = payload.get("type", "")

        if req_type == "ping":
            return {"result": {"status": "ok"}, "error": None}

        if req_type != "tool_execution":
            return {"error": f"Unknown request type: {req_type}", "result": None}

        tool_name = payload.get("tool_name", "")
        arguments = payload.get("arguments", {})

        tool_fn = self.tools.get(tool_name)
        if tool_fn is None:
            return {"error": f"Unknown tool: {tool_name}", "result": None}

        try:
            result = tool_fn(**arguments)
            return {"result": result, "error": None}
        except Exception as e:
            logger.exception("Tool execution failed: %s", tool_name)
            return {"error": str(e), "result": None}

    async def handle_request(self, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        """Verify signature and execute requested tool (async).

        Runs the (potentially blocking) tool function in a thread pool
        so it never blocks the event loop.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, self.handle_request_sync, body, headers,
        )

    def fastapi_router(self, prefix: str = "/argus/webhook") -> Any:
        """Return a FastAPI APIRouter that handles POST ``{prefix}``."""
        from fastapi import APIRouter, Request
        from fastapi.responses import JSONResponse

        router = APIRouter()

        @router.post(prefix)
        async def _webhook(request: Request) -> JSONResponse:
            body = await request.body()
            headers = dict(request.headers)
            result = await self.handle_request(body, headers)
            status = 200 if result.get("error") is None else 400
            return JSONResponse(result, status_code=status)

        return router

    def flask_blueprint(self, prefix: str = "/argus/webhook") -> Any:
        """Return a Flask Blueprint that handles POST ``{prefix}``."""
        from flask import Blueprint, jsonify, request

        bp = Blueprint("argus_webhook", __name__)

        @bp.route(prefix, methods=["POST"])
        def _webhook():  # type: ignore[no-untyped-def]
            body = request.get_data()
            headers = dict(request.headers)
            result = self.handle_request_sync(body, headers)
            status = 200 if result.get("error") is None else 400
            return jsonify(result), status

        return bp
