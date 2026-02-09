"""REST API endpoints for Argus agent server."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from argus_agent import __version__

router = APIRouter(tags=["api"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/status")
async def system_status() -> dict[str, Any]:
    """Get current system status summary."""
    return {
        "status": "ok",
        "version": __version__,
        "collectors": {
            "system_metrics": "stopped",
            "process_monitor": "stopped",
            "log_watcher": "stopped",
        },
        "agent": {
            "active_conversations": 0,
            "llm_provider": "not_configured",
        },
    }
