"""Webhook handlers for external billing providers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

logger = logging.getLogger("argus.api.webhooks")


@router.post("/polar")
async def polar_webhook(request: Request) -> dict[str, Any]:
    """Handle Polar webhook events (signature-validated)."""
    from argus_agent.billing.polar_service import handle_webhook_event

    payload = await request.body()
    headers = dict(request.headers)

    try:
        result = await handle_webhook_event(payload, headers)
        return result
    except Exception as exc:
        logger.warning("Polar webhook validation failed: %s", exc)
        raise HTTPException(400, "Invalid webhook signature") from exc
