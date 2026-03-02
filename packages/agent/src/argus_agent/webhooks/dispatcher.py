"""HTTP client that sends signed tool execution requests to webhook endpoints."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from argus_agent.webhooks.signing import sign_payload

logger = logging.getLogger("argus.webhooks.dispatcher")


async def dispatch_tool_call(
    webhook_url: str,
    webhook_secret: str,
    timeout_seconds: int,
    tool_name: str,
    tool_args: dict[str, Any],
) -> dict[str, Any]:
    """Send a tool execution request to the webhook URL.

    Returns the parsed JSON response body.  On HTTP or network errors,
    returns a dict with an ``error`` key describing the failure.
    """
    request_id = uuid.uuid4().hex
    payload = json.dumps({
        "type": "tool_execution",
        "tool_name": tool_name,
        "arguments": tool_args,
        "request_id": request_id,
    }).encode()

    headers = sign_payload(payload, webhook_secret)
    headers["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(webhook_url, content=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        logger.warning("Webhook timeout: %s (tool=%s)", webhook_url, tool_name)
        return {"error": f"Webhook timed out after {timeout_seconds}s", "result": None}
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Webhook HTTP error %d: %s (tool=%s)",
            exc.response.status_code, webhook_url, tool_name,
        )
        return {
            "error": f"Webhook returned HTTP {exc.response.status_code}",
            "result": None,
        }
    except Exception as exc:
        logger.exception("Webhook dispatch error: %s (tool=%s)", webhook_url, tool_name)
        return {"error": f"Webhook request failed: {exc}", "result": None}


async def ping_webhook(
    webhook_url: str,
    webhook_secret: str,
    timeout_seconds: int = 10,
) -> tuple[bool, str]:
    """Send a test ping to the webhook URL.

    Returns (success, status_string).
    """
    payload = json.dumps({
        "type": "ping",
        "request_id": uuid.uuid4().hex,
    }).encode()

    headers = sign_payload(payload, webhook_secret)
    headers["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(webhook_url, content=payload, headers=headers)
            resp.raise_for_status()
            return True, "ok"
    except httpx.TimeoutException:
        return False, "timeout"
    except Exception:
        return False, "error"
