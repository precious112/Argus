"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    """A message in the LLM conversation."""

    role: str  # system, user, assistant, tool
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""


@dataclass
class LLMResponse:
    """Response from an LLM completion."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ToolDefinition:
    """Definition of a tool exposed to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'openai', 'anthropic')."""
        ...

    @property
    @abstractmethod
    def max_context_tokens(self) -> int:
        """Maximum context window size in tokens."""
        ...

    @property
    def supports_tool_calling(self) -> bool:
        return True

    @property
    def supports_streaming(self) -> bool:
        return True

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a completion (non-streaming)."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponse]:
        """Run a streaming completion, yielding deltas."""
        ...

    def count_tokens(self, text: str) -> int:
        """Estimate token count. Override for accurate counting."""
        return len(text) // 4
