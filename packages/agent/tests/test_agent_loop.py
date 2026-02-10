"""Tests for the ReAct agent loop."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from argus_agent.agent.loop import AgentLoop
from argus_agent.agent.memory import ConversationMemory
from argus_agent.config import reset_settings
from argus_agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolDefinition
from argus_agent.tools.base import Tool, ToolRisk, _tools, register_tool


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    _tools.clear()
    yield
    _tools.clear()
    reset_settings()


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def max_context_tokens(self) -> int:
        return 128_000

    async def complete(
        self, messages: list[LLMMessage], tools: list[ToolDefinition] | None = None, **kwargs: Any
    ) -> LLMResponse:
        resp = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return resp

    async def stream(
        self, messages: list[LLMMessage], tools: list[ToolDefinition] | None = None, **kwargs: Any
    ) -> AsyncIterator[LLMResponse]:
        resp = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        yield resp


class EchoTool(Tool):
    """Simple tool for testing."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back the input"

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"echoed": kwargs.get("message", "")}


@pytest.mark.asyncio
async def test_simple_text_response():
    """Agent returns a plain text response (no tool calls)."""
    provider = MockProvider(
        [LLMResponse(content="Hello! The system looks healthy.", finish_reason="stop")]
    )
    memory = ConversationMemory()
    events: list[tuple[str, dict]] = []

    async def on_event(event_type: str, data: dict[str, Any]) -> None:
        events.append((event_type, data))

    agent = AgentLoop(provider=provider, memory=memory, on_event=on_event)
    result = await agent.run("How is the system?")

    assert result.content == "Hello! The system looks healthy."
    assert result.rounds == 1
    assert result.tool_calls_made == 0

    # Check events were emitted
    event_types = [e[0] for e in events]
    assert "thinking_start" in event_types
    assert "thinking_end" in event_types
    assert "assistant_message_delta" in event_types


@pytest.mark.asyncio
async def test_tool_call_and_response():
    """Agent calls a tool, then responds."""
    register_tool(EchoTool())

    # First call: tool call, second call: text response
    provider = MockProvider(
        [
            LLMResponse(
                tool_calls=[
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": json.dumps({"message": "test"}),
                        },
                    }
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="The echo tool returned: test", finish_reason="stop"),
        ]
    )
    memory = ConversationMemory()
    events: list[tuple[str, dict]] = []

    async def on_event(event_type: str, data: dict[str, Any]) -> None:
        events.append((event_type, data))

    agent = AgentLoop(provider=provider, memory=memory, on_event=on_event)
    result = await agent.run("Echo test")

    assert result.content == "The echo tool returned: test"
    assert result.tool_calls_made == 1
    assert result.rounds == 2

    # Check tool events
    tool_events = [e for e in events if e[0] == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0][1]["name"] == "echo"

    result_events = [e for e in events if e[0] == "tool_result"]
    assert len(result_events) == 1
    assert result_events[0][1]["result"]["echoed"] == "test"


@pytest.mark.asyncio
async def test_unknown_tool():
    """Agent handles unknown tool gracefully."""
    provider = MockProvider(
        [
            LLMResponse(
                tool_calls=[
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {
                            "name": "nonexistent_tool",
                            "arguments": "{}",
                        },
                    }
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="Tool not found, sorry.", finish_reason="stop"),
        ]
    )
    memory = ConversationMemory()
    agent = AgentLoop(provider=provider, memory=memory)
    result = await agent.run("Use a nonexistent tool")

    assert result.rounds == 2
    # The error result should be in memory
    tool_messages = [m for m in memory.messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert "Unknown tool" in tool_messages[0].content


@pytest.mark.asyncio
async def test_memory_tracking():
    """Agent properly tracks messages in memory."""
    provider = MockProvider([LLMResponse(content="Response text", finish_reason="stop")])
    memory = ConversationMemory()
    agent = AgentLoop(provider=provider, memory=memory)
    await agent.run("Test message")

    assert len(memory.messages) == 2  # user + assistant
    assert memory.messages[0].role == "user"
    assert memory.messages[0].content == "Test message"
    assert memory.messages[1].role == "assistant"
    assert memory.messages[1].content == "Response text"
