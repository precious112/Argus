"""Tests for the webhook ToolRouter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from argus_agent.webhooks.tool_router import HOST_TOOLS, execute_tool

_MOD = "argus_agent.webhooks.tool_router"


@pytest.mark.asyncio
async def test_returns_none_when_not_saas():
    """In self-hosted mode, execute_tool always returns None."""
    with patch(f"{_MOD}._is_saas", return_value=False):
        result = await execute_tool("system_metrics", {}, "tenant1")
        assert result is None


@pytest.mark.asyncio
async def test_returns_none_for_non_host_tool():
    """Non-host tools should not be routed."""
    with patch(f"{_MOD}._is_saas", return_value=True):
        result = await execute_tool("chart_create", {}, "tenant1")
        assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_no_webhook_configured():
    """If no active webhook exists, returns None for local fallback."""
    with (
        patch(f"{_MOD}._is_saas", return_value=True),
        patch(
            f"{_MOD}._get_active_webhook",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await execute_tool("system_metrics", {}, "tenant1")
        assert result is None


@pytest.mark.asyncio
async def test_dispatches_to_webhook_when_configured():
    """When a webhook is configured, the call is dispatched remotely."""
    mock_webhook = {
        "url": "https://example.com/argus/webhook",
        "secret": "secret123",
        "timeout_seconds": 30,
    }
    mock_resp = {"result": {"cpu_percent": 42.0}, "error": None}

    with (
        patch(f"{_MOD}._is_saas", return_value=True),
        patch(
            f"{_MOD}._get_active_webhook",
            new_callable=AsyncMock,
            return_value=mock_webhook,
        ),
        patch(
            f"{_MOD}.dispatch_tool_call",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ),
    ):
        result = await execute_tool("system_metrics", {}, "tenant1")
        assert result == {"cpu_percent": 42.0}


@pytest.mark.asyncio
async def test_returns_error_from_webhook():
    """When the webhook returns an error, it should be passed through."""
    mock_webhook = {
        "url": "https://example.com/argus/webhook",
        "secret": "secret123",
        "timeout_seconds": 30,
    }
    mock_resp = {
        "error": "Webhook timed out after 30s",
        "result": None,
    }

    with (
        patch(f"{_MOD}._is_saas", return_value=True),
        patch(
            f"{_MOD}._get_active_webhook",
            new_callable=AsyncMock,
            return_value=mock_webhook,
        ),
        patch(
            f"{_MOD}.dispatch_tool_call",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ),
    ):
        result = await execute_tool("system_metrics", {}, "tenant1")
        assert result is not None
        assert "error" in result


def test_host_tools_set_contains_expected():
    """Verify the HOST_TOOLS set includes expected tools."""
    expected = {
        "system_metrics", "process_list", "network_connections",
        "log_search", "security_scan", "run_command",
    }
    assert expected.issubset(HOST_TOOLS)


@pytest.mark.asyncio
async def test_all_host_tools_are_routable():
    """Every HOST_TOOL should be routable when webhook is configured."""
    mock_webhook = {
        "url": "https://example.com/argus/webhook",
        "secret": "secret123",
        "timeout_seconds": 30,
    }
    mock_resp = {"result": {"ok": True}, "error": None}

    for tool_name in HOST_TOOLS:
        with (
            patch(f"{_MOD}._is_saas", return_value=True),
            patch(
                f"{_MOD}._get_active_webhook",
                new_callable=AsyncMock,
                return_value=mock_webhook,
            ),
            patch(
                f"{_MOD}.dispatch_tool_call",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            result = await execute_tool(tool_name, {}, "tenant1")
            assert result is not None, f"{tool_name} not routed"
