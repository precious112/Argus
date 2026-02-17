"""OpenAI LLM provider."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from argus_agent.config import LLMConfig
from argus_agent.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolDefinition

logger = logging.getLogger("argus.llm.openai")

# Model context window sizes
_MODEL_CONTEXT: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
}


def _messages_to_openai(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    """Convert internal messages to OpenAI API format."""
    result = []
    for msg in messages:
        m: dict[str, Any] = {"role": msg.role}
        if msg.content:
            m["content"] = msg.content
        if msg.tool_calls:
            m["tool_calls"] = msg.tool_calls
        if msg.tool_call_id:
            m["role"] = "tool"
            m["tool_call_id"] = msg.tool_call_id
            m["content"] = msg.content or ""
        if msg.name:
            m["name"] = msg.name
        result.append(m)
    return result


def _tools_to_openai(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Convert tool definitions to OpenAI function format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _parse_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    """Parse OpenAI tool call objects into our format."""
    result = []
    for tc in tool_calls:
        result.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
        )
    return result


def _is_retryable(exc: Exception) -> bool:
    """Check if an OpenAI exception is retryable."""
    try:
        import openai
        return isinstance(exc, (openai.RateLimitError, openai.APIConnectionError))
    except ImportError:
        return False


class OpenAIProvider(LLMProvider):
    """OpenAI API provider (GPT-4o, GPT-4, etc.)."""

    def __init__(self, config: LLMConfig) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "openai package required. Install with: pip install argus-agent[openai]"
            ) from e

        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url

        self._client = AsyncOpenAI(**kwargs)
        self._config = config
        self._model = config.model

    @property
    def name(self) -> str:
        return "openai"

    @property
    def max_context_tokens(self) -> int:
        return _MODEL_CONTEXT.get(self._model, 128_000)

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a non-streaming completion."""
        params: dict[str, Any] = {
            "model": self._model,
            "messages": _messages_to_openai(messages),
            "temperature": kwargs.get("temperature", self._config.temperature),
            "max_completion_tokens": kwargs.get("max_tokens", self._config.max_tokens),
        }
        if tools:
            params["tools"] = _tools_to_openai(tools)

        try:
            response = await self._client.chat.completions.create(**params)
        except Exception as exc:
            logger.error("OpenAI API error: %s", exc)
            raise LLMError(str(exc), provider="openai", retryable=_is_retryable(exc)) from exc

        if not response.choices:
            logger.warning("OpenAI returned no choices")
            return LLMResponse(finish_reason="error")

        choice = response.choices[0]
        message = choice.message

        return LLMResponse(
            content=message.content or "",
            tool_calls=_parse_tool_calls(message.tool_calls) if message.tool_calls else [],
            finish_reason=choice.finish_reason or "",
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Run a streaming completion, yielding deltas."""
        params: dict[str, Any] = {
            "model": self._model,
            "messages": _messages_to_openai(messages),
            "temperature": kwargs.get("temperature", self._config.temperature),
            "max_completion_tokens": kwargs.get("max_tokens", self._config.max_tokens),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = _tools_to_openai(tools)

        try:
            stream = await self._client.chat.completions.create(**params)
        except Exception as exc:
            logger.error("OpenAI API error (stream): %s", exc)
            raise LLMError(str(exc), provider="openai", retryable=_is_retryable(exc)) from exc

        # Accumulate tool calls across chunks
        tool_call_accum: dict[int, dict[str, Any]] = {}
        finish_reason = ""
        prompt_tokens = 0
        completion_tokens = 0

        async for chunk in stream:
            if chunk.usage:
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            # Yield text content deltas
            if delta.content:
                yield LLMResponse(content=delta.content)

            # Accumulate tool calls
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_accum:
                        tool_call_accum[idx] = {
                            "id": tc_delta.id or "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc_delta.id:
                        tool_call_accum[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_call_accum[idx]["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_call_accum[idx]["function"]["arguments"] += (
                                tc_delta.function.arguments
                            )

        # Always yield final response with usage metrics
        yield LLMResponse(
            tool_calls=[tool_call_accum[i] for i in sorted(tool_call_accum)]
            if tool_call_accum
            else [],
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def count_tokens(self, text: str) -> int:
        """Estimate token count. Uses ~4 chars/token heuristic."""
        return len(text) // 4
