"""Google Gemini LLM provider."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from argus_agent.config import LLMConfig
from argus_agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolDefinition

logger = logging.getLogger("argus.llm.gemini")

_MODEL_CONTEXT: dict[str, int] = {
    "gemini-1.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-pro": 32_000,
}


def _messages_to_gemini(messages: list[LLMMessage]) -> tuple[str, list[dict[str, Any]]]:
    """Convert internal messages to Gemini format.

    Returns (system_instruction, contents).
    """
    system = ""
    contents = []

    for msg in messages:
        if msg.role == "system":
            system = msg.content
            continue

        if msg.role == "tool":
            contents.append({
                "role": "user",
                "parts": [{
                    "function_response": {
                        "name": msg.name or "unknown",
                        "response": {"result": msg.content},
                    }
                }],
            })
            continue

        if msg.role == "assistant" and msg.tool_calls:
            parts: list[dict[str, Any]] = []
            if msg.content:
                parts.append({"text": msg.content})
            for tc in msg.tool_calls:
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                parts.append({
                    "function_call": {
                        "name": tc["function"]["name"],
                        "args": args,
                    }
                })
            contents.append({"role": "model", "parts": parts})
            continue

        role = "model" if msg.role == "assistant" else "user"
        contents.append({
            "role": role,
            "parts": [{"text": msg.content or ""}],
        })

    return system, contents


def _strip_unsupported_schema_fields(schema: Any) -> Any:
    """Recursively remove fields not supported by Gemini's Schema proto."""
    unsupported = {"default", "examples", "title", "$schema", "additionalProperties"}
    if isinstance(schema, dict):
        return {
            k: _strip_unsupported_schema_fields(v)
            for k, v in schema.items()
            if k not in unsupported
        }
    if isinstance(schema, list):
        return [_strip_unsupported_schema_fields(item) for item in schema]
    return schema


def _tools_to_gemini(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Convert tool definitions to Gemini function declarations."""
    declarations = []
    for t in tools:
        declarations.append({
            "name": t.name,
            "description": t.description,
            "parameters": _strip_unsupported_schema_fields(t.parameters),
        })
    return [{"function_declarations": declarations}]


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(self, config: LLMConfig) -> None:
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise ImportError(
                "google-generativeai package required. "
                "Install with: pip install argus-agent[gemini]"
            ) from e

        genai.configure(api_key=config.api_key)
        self._genai = genai
        self._config = config
        self._model = config.model

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def max_context_tokens(self) -> int:
        return _MODEL_CONTEXT.get(self._model, 1_000_000)

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a non-streaming completion."""
        system, contents = _messages_to_gemini(messages)

        model_kwargs: dict[str, Any] = {}
        if system:
            model_kwargs["system_instruction"] = system

        model = self._genai.GenerativeModel(
            self._model,
            **model_kwargs,
        )

        gen_config = {
            "temperature": kwargs.get("temperature", self._config.temperature),
            "max_output_tokens": kwargs.get("max_tokens", self._config.max_tokens),
        }

        tool_config = None
        if tools:
            tool_config = _tools_to_gemini(tools)

        response = await model.generate_content_async(
            contents,
            generation_config=gen_config,
            tools=tool_config,
        )

        text = ""
        tool_calls = []

        for part in response.parts:
            if hasattr(part, "text") and part.text:
                text += part.text
            elif hasattr(part, "function_call"):
                fc = part.function_call
                if not fc.name:
                    continue
                tool_calls.append({
                    "id": f"gemini_{fc.name}",
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(dict(fc.args)) if fc.args else "{}",
                    },
                })

        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        completion_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        return LLMResponse(
            content=text,
            tool_calls=tool_calls,
            finish_reason="stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Run a streaming completion, yielding deltas."""
        system, contents = _messages_to_gemini(messages)

        model_kwargs: dict[str, Any] = {}
        if system:
            model_kwargs["system_instruction"] = system

        model = self._genai.GenerativeModel(
            self._model,
            **model_kwargs,
        )

        gen_config = {
            "temperature": kwargs.get("temperature", self._config.temperature),
            "max_output_tokens": kwargs.get("max_tokens", self._config.max_tokens),
        }

        tool_config = None
        if tools:
            tool_config = _tools_to_gemini(tools)

        response = await model.generate_content_async(
            contents,
            generation_config=gen_config,
            tools=tool_config,
            stream=True,
        )

        tool_calls = []
        async for chunk in response:
            for part in chunk.parts:
                if hasattr(part, "text") and part.text:
                    yield LLMResponse(content=part.text)
                elif hasattr(part, "function_call"):
                    fc = part.function_call
                    if not fc.name:
                        continue
                    tool_calls.append({
                        "id": f"gemini_{fc.name}",
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args)) if fc.args else "{}",
                        },
                    })

        # Yield final with tool calls
        yield LLMResponse(
            tool_calls=tool_calls,
            finish_reason="stop",
        )
