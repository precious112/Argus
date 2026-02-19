"""Tests for OpenAI LLM provider."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.config import LLMConfig
from argus_agent.llm.base import LLMError, LLMMessage, ToolDefinition

# --- Helpers ---


def _make_config(**overrides: Any) -> LLMConfig:
    defaults = {"provider": "openai", "model": "gpt-4o", "api_key": "test-key"}
    defaults.update(overrides)
    return LLMConfig(**defaults)


@dataclass
class _Function:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    type: str = "function"
    function: _Function | None = None


@dataclass
class _Usage:
    prompt_tokens: int = 100
    completion_tokens: int = 50


@dataclass
class _Message:
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None


@dataclass
class _Choice:
    message: _Message | None = None
    finish_reason: str = "stop"


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = _Usage()


# Streaming helpers

@dataclass
class _DeltaFunction:
    name: str | None = None
    arguments: str | None = None


@dataclass
class _DeltaToolCall:
    index: int
    id: str | None = None
    function: _DeltaFunction | None = None


@dataclass
class _Delta:
    content: str | None = None
    tool_calls: list[_DeltaToolCall] | None = None


@dataclass
class _StreamChoice:
    delta: _Delta
    finish_reason: str | None = None


@dataclass
class _StreamChunk:
    choices: list[_StreamChoice] = field(default_factory=list)
    usage: _Usage | None = None


# --- Message conversion ---


def test_messages_to_openai_basic():
    from argus_agent.llm.openai import _messages_to_openai

    msgs = [
        LLMMessage(role="system", content="You are helpful"),
        LLMMessage(role="user", content="Hello"),
    ]
    result = _messages_to_openai(msgs)
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "You are helpful"
    assert result[1]["role"] == "user"


def test_messages_to_openai_assistant_with_tool_calls():
    from argus_agent.llm.openai import _messages_to_openai

    tool_calls = [{
        "id": "tc_1",
        "type": "function",
        "function": {"name": "get_metrics", "arguments": '{"limit": 10}'},
    }]
    msgs = [
        LLMMessage(role="assistant", content="Let me check", tool_calls=tool_calls),
    ]
    result = _messages_to_openai(msgs)
    assert result[0]["role"] == "assistant"
    assert result[0]["tool_calls"] == tool_calls
    assert result[0]["content"] == "Let me check"


def test_messages_to_openai_tool_result():
    from argus_agent.llm.openai import _messages_to_openai

    msgs = [
        LLMMessage(role="tool", content='{"ok": true}', tool_call_id="tc_1", name="get_metrics"),
    ]
    result = _messages_to_openai(msgs)
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "tc_1"
    assert result[0]["content"] == '{"ok": true}'


# --- Tool conversion ---


def test_tools_to_openai():
    from argus_agent.llm.openai import _tools_to_openai

    tools = [ToolDefinition(name="test", description="A test tool", parameters={"type": "object"})]
    result = _tools_to_openai(tools)
    assert len(result) == 1
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "test"
    assert result[0]["function"]["description"] == "A test tool"
    assert result[0]["function"]["parameters"] == {"type": "object"}


# --- Parse tool calls ---


def test_parse_tool_calls():
    from argus_agent.llm.openai import _parse_tool_calls

    tcs = [
        _ToolCall(id="tc_1", function=_Function(name="get_metrics", arguments='{"limit": 5}')),
        _ToolCall(id="tc_2", function=_Function(name="list_alerts", arguments="{}")),
    ]
    result = _parse_tool_calls(tcs)
    assert len(result) == 2
    assert result[0]["id"] == "tc_1"
    assert result[0]["function"]["name"] == "get_metrics"
    assert result[0]["function"]["arguments"] == '{"limit": 5}'
    assert result[1]["id"] == "tc_2"


# --- Provider init ---


def test_openai_provider_properties():
    mock_module = MagicMock()
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())
        assert provider.name == "openai"
        assert provider.max_context_tokens == 128_000


def test_openai_unknown_model_context():
    mock_module = MagicMock()
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config(model="gpt-future"))
        assert provider.max_context_tokens == 128_000


# --- Complete ---


@pytest.mark.asyncio
async def test_openai_complete_text_response():
    """complete() returns text content from response."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_Response(
            choices=[_Choice(message=_Message(content="Hello world"))],
        )
    )

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())

    provider._client = mock_client
    msgs = [LLMMessage(role="user", content="Hi")]
    result = await provider.complete(msgs)

    assert result.content == "Hello world"
    assert result.finish_reason == "stop"
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50


@pytest.mark.asyncio
async def test_openai_complete_with_tool_calls():
    """complete() parses tool call objects."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_Response(
            choices=[_Choice(
                message=_Message(
                    tool_calls=[
                        _ToolCall(
                            id="tc_1",
                            function=_Function(name="get_metrics", arguments='{"limit": 5}'),
                        ),
                    ],
                ),
                finish_reason="tool_calls",
            )],
        )
    )

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())

    provider._client = mock_client
    tools = [ToolDefinition(
        name="get_metrics", description="Get metrics",
        parameters={"type": "object"},
    )]
    msgs = [LLMMessage(role="user", content="metrics")]
    result = await provider.complete(msgs, tools=tools)

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc["function"]["name"] == "get_metrics"
    assert json.loads(tc["function"]["arguments"]) == {"limit": 5}
    assert result.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_openai_complete_empty_choices():
    """complete() handles empty choices list gracefully."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_Response(choices=[]),
    )

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())

    provider._client = mock_client
    msgs = [LLMMessage(role="user", content="Hi")]
    result = await provider.complete(msgs)

    assert result.finish_reason == "error"
    assert result.content == ""


@pytest.mark.asyncio
async def test_openai_complete_api_error():
    """complete() wraps API errors in LLMError."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API key invalid"),
    )

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())

    provider._client = mock_client
    msgs = [LLMMessage(role="user", content="Hi")]

    with pytest.raises(LLMError) as exc_info:
        await provider.complete(msgs)
    assert exc_info.value.provider == "openai"
    assert "API key invalid" in str(exc_info.value)


# --- Stream ---


@pytest.mark.asyncio
async def test_openai_stream_text_deltas():
    """stream() yields text deltas and final usage."""
    chunks = [
        _StreamChunk(choices=[_StreamChoice(delta=_Delta(content="Hello "))]),
        _StreamChunk(choices=[_StreamChoice(delta=_Delta(content="world"))]),
        _StreamChunk(
            choices=[_StreamChoice(delta=_Delta(), finish_reason="stop")],
            usage=_Usage(prompt_tokens=80, completion_tokens=20),
        ),
    ]

    class _AsyncStream:
        async def __aiter__(self):
            for c in chunks:
                yield c

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_AsyncStream())

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())

    provider._client = mock_client

    responses = []
    async for r in provider.stream([LLMMessage(role="user", content="Hi")]):
        responses.append(r)

    # Two text deltas + one final
    assert len(responses) == 3
    assert responses[0].content == "Hello "
    assert responses[1].content == "world"
    assert responses[2].finish_reason == "stop"
    assert responses[2].prompt_tokens == 80
    assert responses[2].completion_tokens == 20


@pytest.mark.asyncio
async def test_openai_stream_tool_calls():
    """stream() accumulates tool calls across chunks."""
    chunks = [
        _StreamChunk(choices=[_StreamChoice(delta=_Delta(
            tool_calls=[_DeltaToolCall(
                index=0,
                id="tc_1",
                function=_DeltaFunction(name="get_metrics", arguments='{"li'),
            )],
        ))]),
        _StreamChunk(choices=[_StreamChoice(delta=_Delta(
            tool_calls=[_DeltaToolCall(
                index=0,
                function=_DeltaFunction(arguments='mit": 5}'),
            )],
        ))]),
        _StreamChunk(
            choices=[_StreamChoice(delta=_Delta(), finish_reason="tool_calls")],
        ),
    ]

    class _AsyncStream:
        async def __aiter__(self):
            for c in chunks:
                yield c

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_AsyncStream())

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())

    provider._client = mock_client

    responses = []
    async for r in provider.stream([LLMMessage(role="user", content="metrics")]):
        responses.append(r)

    # Only the final response (no text deltas)
    assert len(responses) == 1
    final = responses[0]
    assert final.finish_reason == "tool_calls"
    assert len(final.tool_calls) == 1
    assert final.tool_calls[0]["id"] == "tc_1"
    assert final.tool_calls[0]["function"]["name"] == "get_metrics"
    assert json.loads(final.tool_calls[0]["function"]["arguments"]) == {"limit": 5}


@pytest.mark.asyncio
async def test_openai_stream_empty_yields_final():
    """stream() always yields a final response even with no text or tool calls."""
    chunks = [
        _StreamChunk(choices=[]),  # empty choices chunk (usage-only)
    ]

    class _AsyncStream:
        async def __aiter__(self):
            for c in chunks:
                yield c

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_AsyncStream())

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())

    provider._client = mock_client

    responses = []
    async for r in provider.stream([LLMMessage(role="user", content="Hi")]):
        responses.append(r)

    # Should always yield at least the final response
    assert len(responses) == 1
    assert responses[0].tool_calls == []


@pytest.mark.asyncio
async def test_fixed_temp_model_omits_temperature():
    """Models in _FIXED_TEMPERATURE_PREFIXES should not send temperature."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_Response(
            choices=[_Choice(message=_Message(content="ok"))],
        )
    )

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config(model="gpt-5-mini"))

    provider._client = mock_client
    await provider.complete([LLMMessage(role="user", content="Hi")])

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert "temperature" not in call_kwargs


@pytest.mark.asyncio
async def test_normal_model_includes_temperature():
    """Normal models should include temperature in API params."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_Response(
            choices=[_Choice(message=_Message(content="ok"))],
        )
    )

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config(model="gpt-4o"))

    provider._client = mock_client
    await provider.complete([LLMMessage(role="user", content="Hi")])

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert "temperature" in call_kwargs
    assert call_kwargs["temperature"] == 0.1


@pytest.mark.asyncio
async def test_openai_stream_api_error():
    """stream() wraps API errors in LLMError."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=Exception("rate limit exceeded"),
    )

    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_module}):
        from importlib import reload

        import argus_agent.llm.openai as mod

        reload(mod)
        provider = mod.OpenAIProvider(_make_config())

    provider._client = mock_client

    with pytest.raises(LLMError) as exc_info:
        async for _ in provider.stream([LLMMessage(role="user", content="Hi")]):
            pass
    assert exc_info.value.provider == "openai"
