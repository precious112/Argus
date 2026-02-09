"""LLM provider discovery and registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from argus_agent.config import get_settings

if TYPE_CHECKING:
    from argus_agent.llm.base import LLMProvider

logger = logging.getLogger("argus.llm")

_providers: dict[str, type[LLMProvider]] = {}


def register_provider(name: str, cls: type[LLMProvider]) -> None:
    """Register an LLM provider class."""
    _providers[name] = cls
    logger.debug("Registered LLM provider: %s", name)


def get_provider() -> LLMProvider:
    """Get the configured LLM provider instance."""
    settings = get_settings()
    provider_name = settings.llm.provider

    if provider_name not in _providers:
        _discover_providers()

    if provider_name not in _providers:
        raise ValueError(
            f"Unknown LLM provider: {provider_name}. Available: {list(_providers.keys())}"
        )

    return _providers[provider_name](settings.llm)


def _discover_providers() -> None:
    """Auto-discover available providers based on installed packages."""
    try:
        from argus_agent.llm.openai import OpenAIProvider

        register_provider("openai", OpenAIProvider)
    except ImportError:
        pass

    try:
        from argus_agent.llm.anthropic import AnthropicProvider

        register_provider("anthropic", AnthropicProvider)
    except ImportError:
        pass

    try:
        from argus_agent.llm.gemini import GeminiProvider

        register_provider("gemini", GeminiProvider)
    except ImportError:
        pass
