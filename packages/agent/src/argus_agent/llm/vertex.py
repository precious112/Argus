"""Vertex AI (Gemini on GCP) LLM provider.

Runs the same Gemini models as the native ``gemini`` provider, but through
Google Cloud Vertex AI instead of the Gemini Developer API. This exists because
the Gemini Developer API is heavily rate-limited for some accounts, while Vertex
AI offers separate quota. The two are distinct backends with different auth:

- ``gemini``  → API key (``GEMINI_API_KEY``-style), Gemini Developer API.
- ``vertex``  → GCP project + location + Application Default Credentials
  (``gcloud auth application-default login`` or a service account), Vertex AI.

The message/tool/response shapes are identical between the two backends, so this
provider reuses the native Gemini conversion helpers and only swaps the client,
auth, and tool/`Content` object construction that Vertex's typed SDK requires.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from argus_agent.config import LLMConfig
from argus_agent.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolDefinition
from argus_agent.llm.gemini import (
    _MODEL_CONTEXT,
    _deep_convert,
    _is_retryable,
    _messages_to_gemini,
    _strip_unsupported_schema_fields,
)

logger = logging.getLogger("argus.llm.vertex")


def _tools_to_vertex(tools: list[ToolDefinition]) -> list[Any]:
    """Convert tool definitions to Vertex AI Tool/FunctionDeclaration objects."""
    from vertexai.generative_models import FunctionDeclaration, Tool

    declarations = [
        FunctionDeclaration(
            name=t.name,
            description=t.description,
            parameters=_strip_unsupported_schema_fields(t.parameters),
        )
        for t in tools
    ]
    return [Tool(function_declarations=declarations)]


def _part_text(part: Any) -> str:
    """Safely read a Vertex Part's text (raises on non-text parts)."""
    try:
        return part.text or ""
    except (AttributeError, ValueError):
        return ""


def _part_function_call(part: Any) -> dict[str, Any] | None:
    """Convert a Vertex function_call part to our internal tool-call format."""
    fc = getattr(part, "function_call", None)
    if not fc or not getattr(fc, "name", ""):
        return None
    args = _deep_convert(fc.args) if fc.args else {}
    return {
        "id": f"vertex_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {"name": fc.name, "arguments": json.dumps(args)},
    }


class VertexProvider(LLMProvider):
    """Gemini-on-Vertex-AI provider (GCP project/location + ADC auth)."""

    def __init__(self, config: LLMConfig) -> None:
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
        except ImportError as e:
            raise ImportError(
                "google-cloud-aiplatform package required. "
                "Install with: pip install argus-agent[vertex]"
            ) from e

        init_kwargs: dict[str, Any] = {"location": config.vertex_location or "us-central1"}
        if config.vertex_project:
            init_kwargs["project"] = config.vertex_project
        # Project/location may also come from GOOGLE_CLOUD_PROJECT/LOCATION env vars
        # and credentials from Application Default Credentials.
        vertexai.init(**init_kwargs)

        self._GenerativeModel = GenerativeModel
        self._config = config
        self._model = config.model

    @property
    def name(self) -> str:
        return "vertex"

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_context_tokens(self) -> int:
        return _MODEL_CONTEXT.get(self._model, 1_000_000)

    def _build_model(self, system: str) -> Any:
        model_kwargs: dict[str, Any] = {}
        if system:
            model_kwargs["system_instruction"] = system
        return self._GenerativeModel(self._model, **model_kwargs)

    def _gen_config(self, kwargs: dict[str, Any]) -> Any:
        from vertexai.generative_models import GenerationConfig

        return GenerationConfig(
            temperature=kwargs.get("temperature", self._config.temperature),
            max_output_tokens=kwargs.get("max_tokens", self._config.max_tokens),
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a non-streaming completion."""
        system, contents = _messages_to_gemini(messages)
        model = self._build_model(system)
        tools_arg = _tools_to_vertex(tools) if tools else None

        try:
            response = await model.generate_content_async(
                contents,
                generation_config=self._gen_config(kwargs),
                tools=tools_arg,
            )
        except Exception as exc:
            logger.error("Vertex AI error: %s", exc)
            raise LLMError(str(exc), provider="vertex", retryable=_is_retryable(exc)) from exc

        text = ""
        tool_calls: list[dict[str, Any]] = []
        candidate = None
        try:
            candidate = response.candidates[0]
            parts = candidate.content.parts
        except (ValueError, IndexError, AttributeError):
            logger.warning("Vertex AI returned no content (possibly blocked)")
            parts = []

        for part in parts:
            t = _part_text(part)
            if t:
                text += t
                continue
            call = _part_function_call(part)
            if call:
                tool_calls.append(call)

        # Preserve the raw model Content (carries thought_signatures) so a
        # follow-up tool-call turn can replay it verbatim.
        metadata: dict[str, Any] = {}
        if tool_calls and candidate is not None:
            try:
                metadata["_gemini_content"] = candidate.content
            except (AttributeError, IndexError):
                logger.debug("Could not capture Vertex raw content for thought_signatures")

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
        model = self._build_model(system)
        tools_arg = _tools_to_vertex(tools) if tools else None

        try:
            response = await model.generate_content_async(
                contents,
                generation_config=self._gen_config(kwargs),
                tools=tools_arg,
                stream=True,
            )
        except Exception as exc:
            logger.error("Vertex AI error (stream): %s", exc)
            raise LLMError(str(exc), provider="vertex", retryable=_is_retryable(exc)) from exc

        tool_calls: list[dict[str, Any]] = []
        raw_parts: list[Any] = []
        prompt_tokens = 0
        completion_tokens = 0

        async for chunk in response:
            try:
                parts = chunk.candidates[0].content.parts
            except (ValueError, IndexError, AttributeError):
                parts = []
            for part in parts:
                raw_parts.append(part)
                t = _part_text(part)
                if t:
                    yield LLMResponse(content=t)
                    continue
                call = _part_function_call(part)
                if call:
                    tool_calls.append(call)

            usage = getattr(chunk, "usage_metadata", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_token_count", prompt_tokens)
                completion_tokens = getattr(usage, "candidates_token_count", completion_tokens)

        # Rebuild the raw model Content to preserve thought_signatures.
        metadata: dict[str, Any] = {}
        if tool_calls and raw_parts:
            try:
                from vertexai.generative_models import Content

                metadata["_gemini_content"] = Content(role="model", parts=raw_parts)
            except Exception:
                logger.debug(
                    "Could not build Vertex raw content for thought_signatures",
                    exc_info=True,
                )

        yield LLMResponse(
            tool_calls=tool_calls,
            finish_reason="stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            metadata=metadata,
        )
