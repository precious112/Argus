"""Tests for the AI investigation pipeline."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest

from argus_agent.agent.investigator import MAX_CONCURRENT, Investigator
from argus_agent.config import AIBudgetConfig, reset_settings
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType
from argus_agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolDefinition
from argus_agent.scheduler.budget import TokenBudget
from argus_agent.tools.base import _tools


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, response_text: str = "Investigation complete.") -> None:
        self._response_text = response_text

    @property
    def name(self) -> str:
        return "mock"

    @property
    def max_context_tokens(self) -> int:
        return 128_000

    async def complete(
        self, messages: list[LLMMessage], tools: list[ToolDefinition] | None = None, **kwargs: Any
    ) -> LLMResponse:
        return LLMResponse(
            content=self._response_text,
            finish_reason="stop",
            prompt_tokens=100,
            completion_tokens=50,
        )

    async def stream(
        self, messages: list[LLMMessage], tools: list[ToolDefinition] | None = None, **kwargs: Any
    ) -> AsyncIterator[LLMResponse]:
        yield LLMResponse(
            content=self._response_text,
            finish_reason="stop",
            prompt_tokens=100,
            completion_tokens=50,
        )


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    _tools.clear()
    yield
    _tools.clear()
    reset_settings()


@pytest.fixture
def budget():
    return TokenBudget(AIBudgetConfig(
        daily_token_limit=100_000,
        hourly_token_limit=20_000,
        priority_reserve=0.3,
    ))


@pytest.fixture
def provider():
    return MockProvider()


@pytest.fixture
def ws_manager():
    mgr = AsyncMock()
    mgr.broadcast = AsyncMock()
    return mgr


@pytest.fixture
def investigator(budget, provider, ws_manager):
    return Investigator(budget=budget, provider=provider, ws_manager=ws_manager)


def _make_event(severity=EventSeverity.URGENT):
    return Event(
        source=EventSource.SYSTEM_METRICS,
        type=EventType.CPU_HIGH,
        severity=severity,
        message="CPU at 99%",
        data={"cpu_percent": 99.0},
    )


@pytest.mark.asyncio
async def test_investigate_event_runs(investigator: Investigator, ws_manager):
    await investigator.investigate_event(_make_event())

    # Should broadcast start and end
    broadcasts = ws_manager.broadcast.call_args_list
    types = [call[0][0].type for call in broadcasts]
    assert "investigation_start" in types
    assert "investigation_end" in types


@pytest.mark.asyncio
async def test_investigate_records_budget(investigator: Investigator, budget: TokenBudget):
    await investigator.investigate_event(_make_event())

    status = budget.get_status()
    assert status["total_tokens"] > 0
    assert status["total_requests"] > 0


@pytest.mark.asyncio
async def test_investigate_budget_rejected(ws_manager):
    """Investigation skipped when budget is exhausted."""
    budget = TokenBudget(AIBudgetConfig(
        daily_token_limit=100,
        hourly_token_limit=50,
        priority_reserve=0.0,
    ))
    # Exhaust the budget
    budget.record_usage(50, 50, source="test")

    inv = Investigator(budget=budget, provider=MockProvider(), ws_manager=ws_manager)
    await inv.investigate_event(_make_event())

    # Should not broadcast anything (skipped)
    ws_manager.broadcast.assert_not_called()


@pytest.mark.asyncio
async def test_investigate_no_provider(budget: TokenBudget, ws_manager):
    """Investigation skipped when no LLM provider."""
    inv = Investigator(budget=budget, provider=None, ws_manager=ws_manager)
    await inv.investigate_event(_make_event())

    # Only broadcast check — no investigation start/end because provider is None
    ws_manager.broadcast.assert_not_called()


@pytest.mark.asyncio
async def test_investigation_prompt_contains_event_data(investigator: Investigator):
    event = _make_event()
    prompt = investigator._build_prompt(event)

    assert "CPU at 99%" in prompt
    assert "cpu_high" in prompt
    assert "URGENT" in prompt


@pytest.mark.asyncio
async def test_periodic_review(investigator: Investigator, ws_manager):
    await investigator.periodic_review()

    broadcasts = ws_manager.broadcast.call_args_list
    assert len(broadcasts) > 0


@pytest.mark.asyncio
async def test_periodic_review_budget_skip(ws_manager):
    """Periodic review skipped when budget insufficient."""
    budget = TokenBudget(AIBudgetConfig(
        daily_token_limit=100,
        hourly_token_limit=50,
        priority_reserve=0.3,
    ))
    budget.record_usage(30, 30, source="test")

    inv = Investigator(budget=budget, provider=MockProvider(), ws_manager=ws_manager)
    await inv.periodic_review()

    ws_manager.broadcast.assert_not_called()


@pytest.mark.asyncio
async def test_daily_digest(investigator: Investigator, ws_manager):
    await investigator.daily_digest()

    broadcasts = ws_manager.broadcast.call_args_list
    assert len(broadcasts) > 0


@pytest.mark.asyncio
async def test_max_concurrent_limit(budget, provider, ws_manager):
    """Only MAX_CONCURRENT investigations run simultaneously."""
    inv = Investigator(budget=budget, provider=provider, ws_manager=ws_manager)

    # Fill up the concurrency slots
    async with inv._lock:
        inv._active = MAX_CONCURRENT

    # This should be skipped
    await inv.investigate_event(_make_event())

    # No investigation start broadcast since we're at max
    start_broadcasts = [
        call for call in ws_manager.broadcast.call_args_list
        if call[0][0].type == "investigation_start"
    ]
    assert len(start_broadcasts) == 0
