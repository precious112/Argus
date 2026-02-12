"""Google Gemini LLM provider."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from argus_agent.config import LLMConfig
from argus_agent.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolDefinition

logger = logging.getLogger("argus.llm.gemini")


def _deep_convert(obj: Any) -> Any:
    """Recursively convert protobuf MapComposite/RepeatedComposite to plain Python types.

    ``dict(fc.args)`` preserves RepeatedComposite for list values, which
    breaks ``json.dumps``.  This helper deep-converts the whole tree.
    """
    if hasattr(obj, "items"):  # MapComposite or dict-like
        return {k: _deep_convert(v) for k, v in obj.items()}
    if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes)):
        return [_deep_convert(v) for v in obj]
    return obj


_MODEL_CONTEXT: dict[str, int] = {
    "gemini-1.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-pro": 32_000,
}


def _messages_to_gemini(messages: list[LLMMessage]) -> tuple[str, list[Any]]:
    """Convert internal messages to Gemini format.

    Returns (system_instruction, contents).
    """
    system = ""
    contents: list[Any] = []

    for msg in messages:
        if msg.role == "system":
            system = msg.content
            continue

        if msg.role == "tool":
            part = {
                "function_response": {
                    "name": msg.name or "unknown",
                    "response": {"result": msg.content},
                }
            }
            # Merge consecutive function responses into a single user turn
            # (Gemini requires all responses for a batch of function_calls in one turn)
            if (
                contents
                and isinstance(contents[-1], dict)
                and contents[-1].get("role") == "user"
                and contents[-1].get("parts")
                and "function_response" in contents[-1]["parts"][0]
            ):
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
            continue

        if msg.role == "assistant" and msg.tool_calls:
            # Use raw Gemini content if available (preserves thought_signatures)
            raw_content = msg.metadata.get("_gemini_content")
            if raw_content is not None:
                contents.append(raw_content)
                continue

            # Fallback: reconstruct from internal format
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


def _is_retryable(exc: Exception) -> bool:
    """Check if a Gemini exception is retryable."""
    try:
        from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
        return isinstance(exc, (ResourceExhausted, ServiceUnavailable))
    except ImportError:
        return False


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

        try:
            response = await model.generate_content_async(
                contents,
                generation_config=gen_config,
                tools=tool_config,
            )
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            raise LLMError(str(exc), provider="gemini", retryable=_is_retryable(exc)) from exc

        text = ""
        tool_calls = []

        # G1: response.parts raises ValueError if response is blocked/empty
        try:
            parts = response.parts
        except (ValueError, IndexError):
            logger.warning("Gemini returned no content (possibly blocked)")
            parts = []

        for part in parts:
            if hasattr(part, "text") and part.text:
                text += part.text
            elif hasattr(part, "function_call"):
                fc = part.function_call
                if not fc.name:
                    continue
                tool_calls.append({
                    "id": f"gemini_{fc.name}_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(_deep_convert(fc.args)) if fc.args else "{}",
                    },
                })

        # Capture raw content to preserve thought_signatures for conversation history
        metadata: dict[str, Any] = {}
        if tool_calls:
            try:
                metadata["_gemini_content"] = response.candidates[0].content
            except (AttributeError, IndexError):
                logger.debug("Could not capture Gemini raw content for thought_signatures")

        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        completion_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        return LLMResponse(
            content=text,
            tool_calls=tool_calls,
            finish_reason="stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            metadata=metadata,
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

        try:
            response = await model.generate_content_async(
                contents,
                generation_config=gen_config,
                tools=tool_config,
                stream=True,
            )
        except Exception as exc:
            logger.error("Gemini API error (stream): %s", exc)
            raise LLMError(str(exc), provider="gemini", retryable=_is_retryable(exc)) from exc

        tool_calls = []
        raw_parts = []
        async for chunk in response:
            for part in chunk.parts:
                raw_parts.append(part)
                if hasattr(part, "text") and part.text:
                    yield LLMResponse(content=part.text)
                elif hasattr(part, "function_call"):
                    fc = part.function_call
                    if not fc.name:
                        continue
                    tool_calls.append({
                        "id": f"gemini_{fc.name}_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(_deep_convert(fc.args)) if fc.args else "{}",
                        },
                    })

        # G2: Capture streaming token usage
        prompt_tokens = 0
        completion_tokens = 0
        try:
            usage = getattr(response, "usage_metadata", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_token_count", 0)
                completion_tokens = getattr(usage, "candidates_token_count", 0)
        except Exception:
            logger.debug("Could not capture Gemini streaming usage metadata")

        # Build raw content to preserve thought_signatures for conversation history
        metadata: dict[str, Any] = {}
        if tool_calls and raw_parts:
            try:
                from google.generativeai import protos
                metadata["_gemini_content"] = protos.Content(
                    role="model",
                    parts=[p._pb for p in raw_parts],
                )
            except Exception:
                logger.debug(
                    "Could not build Gemini raw content for thought_signatures",
                    exc_info=True,
                )

        # Yield final with tool calls and usage
        yield LLMResponse(
            tool_calls=tool_calls,
            finish_reason="stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            metadata=metadata,
        )
