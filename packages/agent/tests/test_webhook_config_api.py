"""Tests for webhook configuration API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from argus_agent.api.webhook_config import (
    _validate_mode,
    _validate_url,
    _webhook_dict,
)


class TestCreateWebhook:
    def test_rejects_invalid_url(self):
        """Should reject URLs without http/https scheme."""
        with pytest.raises(Exception):
            _validate_url("ftp://invalid")

    def test_rejects_empty_host(self):
        with pytest.raises(Exception):
            _validate_url("http://")

    def test_accepts_valid_url(self):
        _validate_url("https://example.com/webhook")

    def test_accepts_http_url(self):
        _validate_url("http://localhost:8080/webhook")


class TestValidateMode:
    def test_rejects_invalid_mode(self):
        with pytest.raises(Exception):
            _validate_mode("invalid_mode")

    def test_accepts_alerts_only(self):
        _validate_mode("alerts_only")

    def test_accepts_tool_execution(self):
        _validate_mode("tool_execution")

    def test_accepts_both(self):
        _validate_mode("both")


class TestWebhookDict:
    def test_serializes_webhook(self):
        """_webhook_dict should produce a serializable dict."""
        from datetime import UTC, datetime

        wh = MagicMock()
        wh.id = "wh1"
        wh.name = "Test"
        wh.url = "https://example.com"
        wh.events = "*"
        wh.mode = "tool_execution"
        wh.remote_tools = "*"
        wh.timeout_seconds = 30
        wh.is_active = True
        wh.last_ping_at = datetime(2026, 1, 1, tzinfo=UTC)
        wh.last_ping_status = "ok"
        wh.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        wh.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

        result = _webhook_dict(wh)
        assert result["id"] == "wh1"
        assert result["name"] == "Test"
        assert result["mode"] == "tool_execution"
        assert result["is_active"] is True
        assert result["last_ping_status"] == "ok"
        assert "2026" in result["last_ping_at"]

    def test_handles_none_timestamps(self):
        wh = MagicMock()
        wh.id = "wh2"
        wh.name = ""
        wh.url = "https://example.com"
        wh.events = "*"
        wh.mode = "alerts_only"
        wh.remote_tools = "*"
        wh.timeout_seconds = 30
        wh.is_active = False
        wh.last_ping_at = None
        wh.last_ping_status = ""
        wh.created_at = None
        wh.updated_at = None

        result = _webhook_dict(wh)
        assert result["last_ping_at"] is None
        assert result["created_at"] is None
