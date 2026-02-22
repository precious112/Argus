"""Tests for TokenUsageService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.storage.token_usage import TokenUsageService, _estimate_cost


class TestEstimateCost:
    def test_known_model(self):
        cost = _estimate_cost("gpt-4o", prompt_tokens=1000, completion_tokens=500)
        # gpt-4o: $0.0025/1K input, $0.01/1K output
        expected = (1000 / 1000) * 0.0025 + (500 / 1000) * 0.01
        assert abs(cost - expected) < 1e-10

    def test_unknown_model_uses_default(self):
        cost = _estimate_cost("some-unknown-model", prompt_tokens=2000, completion_tokens=1000)
        # _default: $0.002/1K input, $0.008/1K output
        expected = (2000 / 1000) * 0.002 + (1000 / 1000) * 0.008
        assert abs(cost - expected) < 1e-10

    def test_zero_tokens(self):
        assert _estimate_cost("gpt-4o", 0, 0) == 0.0

    def test_anthropic_model(self):
        cost = _estimate_cost(
            "claude-sonnet-4-20250514", prompt_tokens=10000, completion_tokens=5000,
        )
        expected = (10000 / 1000) * 0.003 + (5000 / 1000) * 0.015
        assert abs(cost - expected) < 1e-10


class TestTokenUsageServiceRecord:
    def setup_method(self):
        self.svc = TokenUsageService()

    @pytest.mark.asyncio
    async def test_record_inserts_row(self):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock(side_effect=lambda e: setattr(e, "id", 7))

        with patch("argus_agent.storage.token_usage.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            row_id = await self.svc.record(
                prompt_tokens=100,
                completion_tokens=50,
                provider="openai",
                model="gpt-4o",
                source="user_chat",
                conversation_id="conv-1",
            )
            assert row_id == 7
            mock_session.add.assert_called_once()
            added = mock_session.add.call_args[0][0]
            assert added.provider == "openai"
            assert added.model == "gpt-4o"
            assert added.prompt_tokens == 100
            assert added.completion_tokens == 50
            assert added.source == "user_chat"


class TestTokenUsageServiceGetUsageOverTime:
    def setup_method(self):
        self.svc = TokenUsageService()

    @pytest.mark.asyncio
    async def test_returns_aggregated_buckets(self):
        mock_row = MagicMock()
        mock_row.bucket = "2024-01-01 10:00"
        mock_row.prompt_tokens = 500
        mock_row.completion_tokens = 200
        mock_row.total_tokens = 700
        mock_row.request_count = 3

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([mock_row]))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("argus_agent.storage.token_usage.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            data = await self.svc.get_usage_over_time(granularity="hour")
            assert len(data) == 1
            assert data[0]["bucket"] == "2024-01-01 10:00"
            assert data[0]["total_tokens"] == 700
            assert data[0]["request_count"] == 3

    @pytest.mark.asyncio
    async def test_empty_result(self):
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("argus_agent.storage.token_usage.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            data = await self.svc.get_usage_over_time(granularity="day")
            assert data == []


class TestTokenUsageServiceGetUsageByDimension:
    def setup_method(self):
        self.svc = TokenUsageService()

    @pytest.mark.asyncio
    async def test_group_by_provider(self):
        rows = [
            MagicMock(
                prompt_tokens=1000, completion_tokens=500,
                total_tokens=1500, request_count=5,
            ),
            MagicMock(
                prompt_tokens=800, completion_tokens=300,
                total_tokens=1100, request_count=3,
            ),
        ]
        # MagicMock's 'name' attribute is special, set it manually
        rows[0].name = "openai"
        rows[1].name = "anthropic"

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter(rows))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("argus_agent.storage.token_usage.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            data = await self.svc.get_usage_by_dimension(dimension="provider")
            assert len(data) == 2
            assert data[0]["name"] == "openai"
            assert data[1]["name"] == "anthropic"

    @pytest.mark.asyncio
    async def test_empty_dimension(self):
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("argus_agent.storage.token_usage.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            data = await self.svc.get_usage_by_dimension(dimension="source")
            assert data == []


class TestTokenUsageServiceGetSummary:
    def setup_method(self):
        self.svc = TokenUsageService()

    @pytest.mark.asyncio
    async def test_summary_with_data(self):
        # Row for all-time aggregation
        all_row = MagicMock()
        all_row.prompt = 5000
        all_row.completion = 2000
        all_row.total = 7000
        all_row.requests = 10

        # Scalar returns for today/week/month
        today_scalar = 1500
        week_scalar = 4000
        month_scalar = 7000

        # Cost rows
        cost_row = MagicMock()
        cost_row.model = "gpt-4o"
        cost_row.prompt = 5000
        cost_row.completion = 2000

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # all-time
                result.one.return_value = all_row
                return result
            elif call_count == 2:  # today
                result.scalar.return_value = today_scalar
                return result
            elif call_count == 3:  # week
                result.scalar.return_value = week_scalar
                return result
            elif call_count == 4:  # month
                result.scalar.return_value = month_scalar
                return result
            elif call_count == 5:  # cost
                result.all.return_value = [cost_row]
                return result
            return result

        mock_session = AsyncMock()
        mock_session.execute = mock_execute

        with patch("argus_agent.storage.token_usage.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            summary = await self.svc.get_summary()
            assert summary["total_tokens"] == 7000
            assert summary["total_requests"] == 10
            assert summary["prompt_tokens"] == 5000
            assert summary["completion_tokens"] == 2000
            assert summary["avg_tokens_per_request"] == 700
            assert summary["today_tokens"] == 1500
            assert summary["this_week_tokens"] == 4000
            assert summary["this_month_tokens"] == 7000
            assert summary["estimated_cost_usd"] > 0

    @pytest.mark.asyncio
    async def test_summary_empty_db(self):
        all_row = MagicMock()
        all_row.prompt = 0
        all_row.completion = 0
        all_row.total = 0
        all_row.requests = 0

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.one.return_value = all_row
                return result
            elif call_count in (2, 3, 4):
                result.scalar.return_value = 0
                return result
            elif call_count == 5:
                result.all.return_value = []
                return result
            return result

        mock_session = AsyncMock()
        mock_session.execute = mock_execute

        with patch("argus_agent.storage.token_usage.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            summary = await self.svc.get_summary()
            assert summary["total_tokens"] == 0
            assert summary["total_requests"] == 0
            assert summary["avg_tokens_per_request"] == 0
            assert summary["estimated_cost_usd"] == 0
