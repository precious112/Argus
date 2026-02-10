"""Tests for Google Gemini LLM provider."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.config import LLMConfig
from argus_agent.llm.base import LLMMessage, ToolDefinition

# --- Helpers ---


def _make_config(**overrides: Any) -> LLMConfig:
    defaults = {"provider": "gemini", "model": "gemini-1.5-pro", "api_key": "test-key"}
    defaults.update(overrides)
    return LLMConfig(**defaults)


@dataclass
class _FunctionCall:
    name: str
    args: dict[str, Any] | None = None


@dataclass
class _Part:
    text: str | None = None
    function_call: _FunctionCall | None = None


@dataclass
class _UsageMeta:
    prompt_token_count: int = 100
    candidates_token_count: int = 50


@dataclass
class _Response:
    parts: list[_Part]
    usage_metadata: _UsageMeta | None = None

    def __post_init__(self) -> None:
        if self.usage_metadata is None:
            self.usage_metadata = _UsageMeta()


# --- Message conversion ---


def test_messages_to_gemini_system():
    from argus_agent.llm.gemini import _messages_to_gemini

    msgs = [
        LLMMessage(role="system", content="Be helpful"),
        LLMMessage(role="user", content="Hi"),
    ]
    system, contents = _messages_to_gemini(msgs)
    assert system == "Be helpful"
    assert len(contents) == 1
    assert contents[0]["role"] == "user"


def test_messages_to_gemini_assistant_role():
    from argus_agent.llm.gemini import _messages_to_gemini

    msgs = [LLMMessage(role="assistant", content="Hello")]
    _, contents = _messages_to_gemini(msgs)
    assert contents[0]["role"] == "model"


def test_messages_to_gemini_tool_result():
    from argus_agent.llm.gemini import _messages_to_gemini

    msgs = [LLMMessage(role="tool", content="result data", name="my_tool")]
    _, contents = _messages_to_gemini(msgs)
    assert contents[0]["role"] == "user"
    part = contents[0]["parts"][0]
    assert "function_response" in part
    assert part["function_response"]["name"] == "my_tool"


def test_messages_to_gemini_tool_calls():
    from argus_agent.llm.gemini import _messages_to_gemini

    msgs = [
        LLMMessage(
            role="assistant",
            content="Checking",
            tool_calls=[{
                "id": "tc_1",
                "type": "function",
                "function": {"name": "get_metrics", "arguments": '{"limit": 5}'},
            }],
        ),
    ]
    _, contents = _messages_to_gemini(msgs)
    assert contents[0]["role"] == "model"
    parts = contents[0]["parts"]
    assert parts[0]["text"] == "Checking"
    assert parts[1]["function_call"]["name"] == "get_metrics"
    assert parts[1]["function_call"]["args"] == {"limit": 5}


def test_tools_to_gemini():
    from argus_agent.llm.gemini import _tools_to_gemini

    tools = [ToolDefinition(name="test", description="A tool", parameters={"type": "object"})]
    result = _tools_to_gemini(tools)
    assert len(result) == 1
    assert "function_declarations" in result[0]
    assert result[0]["function_declarations"][0]["name"] == "test"


# --- Provider ---


def test_gemini_provider_properties():
    mock_genai = MagicMock()
    with patch.dict("sys.modules", {"google": MagicMock(), "google.generativeai": mock_genai}):
        from importlib import reload

        import argus_agent.llm.gemini as mod

        reload(mod)
        provider = mod.GeminiProvider(_make_config())
        assert provider.name == "gemini"
        assert provider.max_context_tokens == 1_000_000


def test_gemini_unknown_model_context():
    mock_genai = MagicMock()
    with patch.dict("sys.modules", {"google": MagicMock(), "google.generativeai": mock_genai}):
        from importlib import reload

        import argus_agent.llm.gemini as mod

        reload(mod)
        provider = mod.GeminiProvider(_make_config(model="gemini-unknown"))
        assert provider.max_context_tokens == 1_000_000


# --- Complete ---


@pytest.mark.asyncio
async def test_gemini_complete_text():
    mock_genai = MagicMock()
    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(
        return_value=_Response(parts=[_Part(text="Hello world")])
    )
    mock_genai.GenerativeModel.return_value = mock_model

    with patch.dict("sys.modules", {"google": MagicMock(), "google.generativeai": mock_genai}):
        from importlib import reload

        import argus_agent.llm.gemini as mod

        reload(mod)
        provider = mod.GeminiProvider(_make_config())

    provider._genai = mock_genai

    result = await provider.complete([LLMMessage(role="user", content="Hi")])
    assert result.content == "Hello world"
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50


@pytest.mark.asyncio
async def test_gemini_complete_with_tool_calls():
    mock_genai = MagicMock()
    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(
        return_value=_Response(
            parts=[_Part(function_call=_FunctionCall(name="get_metrics", args={"limit": 5}))]
        )
    )
    mock_genai.GenerativeModel.return_value = mock_model

    with patch.dict("sys.modules", {"google": MagicMock(), "google.generativeai": mock_genai}):
        from importlib import reload

        import argus_agent.llm.gemini as mod

        reload(mod)
        provider = mod.GeminiProvider(_make_config())

    provider._genai = mock_genai
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


# --- Stream ---


@pytest.mark.asyncio
async def test_gemini_stream_text():
    @dataclass
    class _Chunk:
        parts: list[_Part]

    class _AsyncResponse:
        async def __aiter__(self):
            yield _Chunk(parts=[_Part(text="Hello ")])
            yield _Chunk(parts=[_Part(text="world")])

    mock_genai = MagicMock()
    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(return_value=_AsyncResponse())
    mock_genai.GenerativeModel.return_value = mock_model

    with patch.dict("sys.modules", {"google": MagicMock(), "google.generativeai": mock_genai}):
        from importlib import reload

        import argus_agent.llm.gemini as mod

        reload(mod)
        provider = mod.GeminiProvider(_make_config())

    provider._genai = mock_genai

    responses = []
    async for r in provider.stream([LLMMessage(role="user", content="Hi")]):
        responses.append(r)

    # Two text deltas + final
    assert len(responses) == 3
    assert responses[0].content == "Hello "
    assert responses[1].content == "world"
    assert responses[2].finish_reason == "stop"


@pytest.mark.asyncio
async def test_gemini_complete_with_system_instruction():
    """Verify system message becomes system_instruction kwarg."""
    mock_genai = MagicMock()
    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(
        return_value=_Response(parts=[_Part(text="ok")])
    )
    mock_genai.GenerativeModel.return_value = mock_model

    with patch.dict("sys.modules", {"google": MagicMock(), "google.generativeai": mock_genai}):
        from importlib import reload

        import argus_agent.llm.gemini as mod

        reload(mod)
        provider = mod.GeminiProvider(_make_config())

    provider._genai = mock_genai

    msgs = [
        LLMMessage(role="system", content="Be concise"),
        LLMMessage(role="user", content="Hi"),
    ]
    await provider.complete(msgs)

    # GenerativeModel should have been called with system_instruction
    mock_genai.GenerativeModel.assert_called_with(
        "gemini-1.5-pro",
        system_instruction="Be concise",
    )
