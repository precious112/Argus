"""Tests for the Vertex AI (Gemini on GCP) LLM provider.

The vertexai SDK is not installed in CI, so these tests mock it via sys.modules.
The provider reuses the native Gemini message/tool conversion, so those paths are
covered by test_gemini_provider; here we focus on the Vertex-specific wiring:
auth/init, candidate-based response parsing, tool calls, streaming, and the
helpful ImportError when the SDK is absent.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.config import LLMConfig
from argus_agent.llm.base import LLMMessage, ToolDefinition
from argus_agent.llm.vertex import VertexProvider


def _make_config(**overrides: Any) -> LLMConfig:
    defaults = {"provider": "vertex", "model": "gemini-2.5-pro"}
    defaults.update(overrides)
    return LLMConfig(**defaults)


# --- Fake Vertex response objects ---


@dataclass
class _FunctionCall:
    name: str
    args: dict[str, Any] | None = None


@dataclass
class _Part:
    text: str | None = None
    function_call: _FunctionCall | None = None


@dataclass
class _Content:
    parts: list[_Part]
    role: str = "model"


@dataclass
class _Candidate:
    content: _Content


@dataclass
class _UsageMeta:
    prompt_token_count: int = 100
    candidates_token_count: int = 50


@dataclass
class _Response:
    candidates: list[_Candidate]
    usage_metadata: _UsageMeta | None = None

    def __post_init__(self) -> None:
        if self.usage_metadata is None:
            self.usage_metadata = _UsageMeta()


def _patched_modules(mock_model: Any = None) -> tuple[dict[str, Any], MagicMock, MagicMock]:
    """Build a sys.modules patch dict for vertexai + vertexai.generative_models."""
    genmod = MagicMock()
    if mock_model is not None:
        genmod.GenerativeModel.return_value = mock_model
    vertexai = MagicMock()
    vertexai.generative_models = genmod
    return {"vertexai": vertexai, "vertexai.generative_models": genmod}, vertexai, genmod


# --- Init / properties ---


def test_vertex_provider_properties():
    mods, vertexai, _ = _patched_modules(MagicMock())
    with patch.dict(sys.modules, mods):
        provider = VertexProvider(_make_config())
        assert provider.name == "vertex"
        assert provider.max_context_tokens == 1_000_000
        vertexai.init.assert_called_once()


def test_vertex_init_passes_project_and_location():
    mods, vertexai, _ = _patched_modules(MagicMock())
    with patch.dict(sys.modules, mods):
        VertexProvider(_make_config(vertex_project="my-proj", vertex_location="europe-west4"))
    vertexai.init.assert_called_once_with(location="europe-west4", project="my-proj")


def test_vertex_init_omits_empty_project():
    """When no project is configured, it's left to env/ADC (not passed)."""
    mods, vertexai, _ = _patched_modules(MagicMock())
    with patch.dict(sys.modules, mods):
        VertexProvider(_make_config(vertex_project="", vertex_location="us-central1"))
    vertexai.init.assert_called_once_with(location="us-central1")


def test_vertex_unknown_model_context():
    mods, _, _ = _patched_modules(MagicMock())
    with patch.dict(sys.modules, mods):
        provider = VertexProvider(_make_config(model="gemini-unknown"))
        assert provider.max_context_tokens == 1_000_000


def test_vertex_missing_sdk_raises_helpful_error():
    # Setting the module to None makes `import vertexai` raise ImportError.
    with patch.dict(sys.modules, {"vertexai": None, "vertexai.generative_models": None}):
        with pytest.raises(ImportError, match="google-cloud-aiplatform"):
            VertexProvider(_make_config())


# --- Complete ---


@pytest.mark.asyncio
async def test_vertex_complete_text():
    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(
        return_value=_Response(candidates=[_Candidate(_Content([_Part(text="Hello world")]))])
    )
    mods, _, _ = _patched_modules(mock_model)
    with patch.dict(sys.modules, mods):
        provider = VertexProvider(_make_config())
        result = await provider.complete([LLMMessage(role="user", content="Hi")])

    assert result.content == "Hello world"
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50


@pytest.mark.asyncio
async def test_vertex_complete_with_tool_calls():
    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(
        return_value=_Response(candidates=[_Candidate(_Content(
            [_Part(function_call=_FunctionCall(name="get_metrics", args={"limit": 5}))]
        ))])
    )
    mods, _, _ = _patched_modules(mock_model)
    with patch.dict(sys.modules, mods):
        provider = VertexProvider(_make_config())
        tools = [ToolDefinition(
            name="get_metrics", description="Get metrics", parameters={"type": "object"},
        )]
        result = await provider.complete([LLMMessage(role="user", content="metrics")], tools=tools)

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc["function"]["name"] == "get_metrics"
    assert json.loads(tc["function"]["arguments"]) == {"limit": 5}


@pytest.mark.asyncio
async def test_vertex_complete_with_system_instruction():
    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(
        return_value=_Response(candidates=[_Candidate(_Content([_Part(text="ok")]))])
    )
    mods, _, genmod = _patched_modules(mock_model)
    with patch.dict(sys.modules, mods):
        provider = VertexProvider(_make_config(model="gemini-2.5-pro"))
        await provider.complete([
            LLMMessage(role="system", content="Be concise"),
            LLMMessage(role="user", content="Hi"),
        ])

    genmod.GenerativeModel.assert_called_with("gemini-2.5-pro", system_instruction="Be concise")


@pytest.mark.asyncio
async def test_vertex_complete_handles_blocked_response():
    """A response with no candidates (blocked) yields empty content, not a crash."""
    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(return_value=_Response(candidates=[]))
    mods, _, _ = _patched_modules(mock_model)
    with patch.dict(sys.modules, mods):
        provider = VertexProvider(_make_config())
        result = await provider.complete([LLMMessage(role="user", content="Hi")])

    assert result.content == ""
    assert result.tool_calls == []


# --- Stream ---


@pytest.mark.asyncio
async def test_vertex_stream_text():
    @dataclass
    class _Chunk:
        candidates: list[_Candidate]
        usage_metadata: Any = None

    class _AsyncResponse:
        async def __aiter__(self):
            yield _Chunk(
                candidates=[_Candidate(_Content([_Part(text="Hello ")]))],
                usage_metadata=_UsageMeta(),
            )
            yield _Chunk(
                candidates=[_Candidate(_Content([_Part(text="world")]))],
                usage_metadata=_UsageMeta(),
            )

    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(return_value=_AsyncResponse())
    mods, _, _ = _patched_modules(mock_model)
    with patch.dict(sys.modules, mods):
        provider = VertexProvider(_make_config())
        responses = []
        async for r in provider.stream([LLMMessage(role="user", content="Hi")]):
            responses.append(r)

    # Two text deltas + final summary
    assert len(responses) == 3
    assert responses[0].content == "Hello "
    assert responses[1].content == "world"
    assert responses[2].finish_reason == "stop"
    assert responses[2].prompt_tokens == 100
    assert responses[2].completion_tokens == 50
