"""Serverless runtime detection and invocation lifecycle helpers."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# Module-level cold start detection
_initialized = False


@dataclass
class ServerlessContext:
    """Context for the current serverless invocation."""

    runtime: str = ""
    function_name: str = ""
    region: str = ""
    memory_limit_mb: int = 0
    invocation_id: str = ""
    is_cold_start: bool = False
    deployment_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "runtime": self.runtime,
            "function_name": self.function_name,
            "is_cold_start": self.is_cold_start,
        }
        if self.region:
            d["region"] = self.region
        if self.memory_limit_mb:
            d["memory_limit_mb"] = self.memory_limit_mb
        if self.invocation_id:
            d["invocation_id"] = self.invocation_id
        if self.deployment_id:
            d["deployment_id"] = self.deployment_id
        if self.extra:
            d.update(self.extra)
        return d


def detect_runtime() -> str | None:
    """Detect the serverless runtime from environment variables.

    Returns one of: "aws_lambda", "vercel", "gcp_functions",
    "cloudflare_workers", or None if not in a serverless environment.
    """
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return "aws_lambda"
    if os.environ.get("VERCEL"):
        return "vercel"
    if os.environ.get("FUNCTION_TARGET") or os.environ.get("K_SERVICE"):
        return "gcp_functions"
    if os.environ.get("CF_PAGES") or os.environ.get("WORKERS_RS_VERSION"):
        return "cloudflare_workers"
    return None


def _build_context(runtime: str) -> ServerlessContext:
    """Build a ServerlessContext from environment variables."""
    global _initialized

    is_cold_start = not _initialized
    _initialized = True

    ctx = ServerlessContext(
        runtime=runtime,
        is_cold_start=is_cold_start,
    )

    if runtime == "aws_lambda":
        ctx.function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "")
        ctx.region = os.environ.get("AWS_REGION", "")
        ctx.memory_limit_mb = int(os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "0"))
        ctx.deployment_id = os.environ.get("AWS_LAMBDA_FUNCTION_VERSION", "")
    elif runtime == "vercel":
        ctx.function_name = os.environ.get("VERCEL_URL", "")
        ctx.region = os.environ.get("VERCEL_REGION", "")
        ctx.deployment_id = os.environ.get("VERCEL_DEPLOYMENT_ID", os.environ.get("VERCEL_GIT_COMMIT_SHA", ""))
    elif runtime == "gcp_functions":
        ctx.function_name = os.environ.get("FUNCTION_TARGET", os.environ.get("K_SERVICE", ""))
        ctx.region = os.environ.get("FUNCTION_REGION", "")
        ctx.memory_limit_mb = int(os.environ.get("FUNCTION_MEMORY_MB", "0"))
        ctx.deployment_id = os.environ.get("K_REVISION", "")
    elif runtime == "cloudflare_workers":
        ctx.function_name = os.environ.get("CF_PAGES_BRANCH", "worker")

    return ctx


# Active invocation tracking
_active_invocation: dict[str, Any] | None = None


def start_invocation(
    function_name: str = "",
    invocation_id: str = "",
) -> str:
    """Start tracking a serverless invocation.

    Call at the beginning of your function handler.
    Returns the invocation_id for correlation.
    """
    global _active_invocation

    inv_id = invocation_id or str(uuid.uuid4())
    _active_invocation = {
        "invocation_id": inv_id,
        "function_name": function_name,
        "start_time": time.monotonic(),
        "start_timestamp": time.time(),
    }

    # Send invocation_start event
    from argus import _client

    if _client:
        ctx = _client._serverless_context
        event_data: dict[str, Any] = {
            "invocation_id": inv_id,
            "function_name": function_name,
        }
        if ctx:
            event_data.update(ctx.to_dict())
        _client.send_event("invocation_start", event_data)

    return inv_id


def end_invocation(
    status: str = "ok",
    error: str = "",
) -> None:
    """End tracking the current serverless invocation.

    Call at the end of your function handler.
    """
    global _active_invocation

    if _active_invocation is None:
        return

    duration_ms = (time.monotonic() - _active_invocation["start_time"]) * 1000

    from argus import _client

    if _client:
        ctx = _client._serverless_context
        event_data: dict[str, Any] = {
            "invocation_id": _active_invocation["invocation_id"],
            "function_name": _active_invocation["function_name"],
            "duration_ms": round(duration_ms, 2),
            "status": status,
        }
        if error:
            event_data["error"] = error
        if ctx:
            event_data.update(ctx.to_dict())
        _client.send_event("invocation_end", event_data)

    _active_invocation = None


def get_active_invocation_id() -> str | None:
    """Get the current active invocation ID, if any."""
    if _active_invocation:
        return _active_invocation["invocation_id"]
    return None
