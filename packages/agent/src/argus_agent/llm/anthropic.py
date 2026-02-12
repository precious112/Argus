"""Anthropic Claude LLM provider."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from argus_agent.config import LLMConfig
from argus_agent.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolDefinition

logger = logging.getLogger("argus.llm.anthropic")

_MODEL_CONTEXT: dict[str, int] = {
    "claude-sonnet-4-20250514": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-haiku-20240307": 200_000,
    "claude-3-opus-20240229": 200_000,
}


def _messages_to_anthropic(
    messages: list[LLMMessage],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert internal messages to Anthropic format.

    Returns (system_prompt, messages).
    Anthropic requires system as a separate parameter, not in the messages list.
    Tool results use tool_result content blocks.
    """
    system = ""
    result = []

    for msg in messages:
        if msg.role == "system":
            system = msg.content
            continue

        if msg.role == "tool":
            result.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content or "",
                    }
                ],
            })
            continue

        if msg.role == "assistant" and msg.tool_calls:
            content: list[dict[str, Any]] = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Malformed JSON in tool call arguments for %s, using empty args",
                            tc["function"]["name"],
                        )
                        args = {}
                content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": args,
                })
            result.append({"role": "assistant", "content": content})
            continue

        result.append({
            "role": msg.role,
            "content": msg.content or "",
        })

    return system, result


def _tools_to_anthropic(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Convert tool definitions to Anthropic format."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


def _parse_tool_calls(content_blocks: list[Any]) -> list[dict[str, Any]]:
    """Parse Anthropic tool_use content blocks into our format."""
    result = []
    for block in content_blocks:
        if getattr(block, "type", None) == "tool_use":
            result.append({
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.input),
                },
            })
    return result


def _is_retryable(exc: Exception) -> bool:
    """Check if an Anthropic exception is retryable."""
    try:
        import anthropic
        return isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError))
    except ImportError:
        return False


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(self, config: LLMConfig) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise ImportError(
                "anthropic package required. Install with: pip install argus-agent[anthropic]"
            ) from e

        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url

        self._client = AsyncAnthropic(**kwargs)
        self._config = config
        self._model = config.model

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def max_context_tokens(self) -> int:
        return _MODEL_CONTEXT.get(self._model, 200_000)

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a non-streaming completion."""
        system, msgs = _messages_to_anthropic(messages)
        params: dict[str, Any] = {
            "model": self._model,
            "messages": msgs,
            "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
            "temperature": kwargs.get("temperature", self._config.temperature),
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = _tools_to_anthropic(tools)

        try:
            response = await self._client.messages.create(**params)
        except Exception as exc:
            logger.error("Anthropic API error: %s", exc)
            raise LLMError(str(exc), provider="anthropic", retryable=_is_retryable(exc)) from exc

        text = ""
        tool_calls = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
            elif getattr(block, "type", None) == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    },
                })

        return LLMResponse(
            content=text,
            tool_calls=tool_calls,
            finish_reason=response.stop_reason or "",
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Run a streaming completion, yielding deltas."""
        system, msgs = _messages_to_anthropic(messages)
        params: dict[str, Any] = {
            "model": self._model,
            "messages": msgs,
            "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
            "temperature": kwargs.get("temperature", self._config.temperature),
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = _tools_to_anthropic(tools)

        tool_call_accum: dict[str, dict[str, Any]] = {}
        current_tool_id = ""
        prompt_tokens = 0
        completion_tokens = 0
        finish_reason = ""

        try:
            stream_ctx = self._client.messages.stream(**params)
        except Exception as exc:
            logger.error("Anthropic API error (stream): %s", exc)
            raise LLMError(str(exc), provider="anthropic", retryable=_is_retryable(exc)) from exc

        async with stream_ctx as stream:
            async for event in stream:
                event_type = getattr(event, "type", "")

                if event_type == "message_start":
                    usage = getattr(event.message, "usage", None)
                    if usage:
                        prompt_tokens = getattr(usage, "input_tokens", 0)

                elif event_type == "content_block_start":
                    block = event.content_block
                    if getattr(block, "type", None) == "tool_use":
                        current_tool_id = block.id
                        tool_call_accum[current_tool_id] = {
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": "",
                            },
                        }

                elif event_type == "content_block_delta":
                    delta = event.delta
                    if getattr(delta, "type", None) == "text_delta":
                        yield LLMResponse(content=delta.text)
                    elif getattr(delta, "type", None) == "input_json_delta":
                        if current_tool_id in tool_call_accum:
                            accum = tool_call_accum[current_tool_id]
                            accum["function"]["arguments"] += delta.partial_json

                elif event_type == "message_delta":
                    finish_reason = getattr(event.delta, "stop_reason", "") or ""
                    usage = getattr(event, "usage", None)
                    if usage:
                        completion_tokens = getattr(usage, "output_tokens", 0)

        # Yield final response with accumulated tool calls and usage
        yield LLMResponse(
            tool_calls=list(tool_call_accum.values()) if tool_call_accum else [],
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
