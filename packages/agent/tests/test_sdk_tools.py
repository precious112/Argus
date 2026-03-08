"""Tests for SDK events tool."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from argus_agent.tools.sdk_events import SDKEventsTool


class TestSDKEventsTool:
    def setup_method(self):
        self.tool = SDKEventsTool()

    def test_tool_properties(self):
        assert self.tool.name == "query_sdk_events"
        assert self.tool.risk.value == "READ_ONLY"

    @pytest.mark.asyncio
    async def test_query_events(self):
        mock_repo = MagicMock()
        mock_repo.execute_raw.return_value = [
            (datetime(2024, 1, 1, tzinfo=UTC), "test-app", "log", '{"message": "hello"}'),
            (datetime(2024, 1, 1, tzinfo=UTC), "test-app", "exception", '{"message": "error"}'),
        ]
        with patch("argus_agent.storage.repositories.get_metrics_repository", return_value=mock_repo):
            result = await self.tool.execute(service="test-app", limit=10)
            assert result["count"] == 2
            assert result["events"][0]["service"] == "test-app"

    @pytest.mark.asyncio
    async def test_query_empty(self):
        mock_repo = MagicMock()
        mock_repo.execute_raw.return_value = []
        with patch("argus_agent.storage.repositories.get_metrics_repository", return_value=mock_repo):
            result = await self.tool.execute()
            assert result["count"] == 0
            assert result["events"] == []

    @pytest.mark.asyncio
    async def test_query_not_initialized(self):
        with patch("argus_agent.storage.repositories.get_metrics_repository", side_effect=RuntimeError("not init")):
            result = await self.tool.execute()
            assert "error" in result

    @pytest.mark.asyncio
    async def test_query_with_filters(self):
        mock_repo = MagicMock()
        mock_repo.execute_raw.return_value = []
        with patch("argus_agent.storage.repositories.get_metrics_repository", return_value=mock_repo):
            result = await self.tool.execute(
                service="my-app",
                event_type="exception",
                since_minutes=30,
                limit=5,
            )
            assert result["count"] == 0
            # Verify the query was built with filters
            call_args = mock_repo.execute_raw.call_args
            query = call_args[0][0]
            assert "service = ?" in query
            assert "event_type = ?" in query
