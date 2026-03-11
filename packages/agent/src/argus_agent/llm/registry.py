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


async def get_provider_for_tenant(tenant_id: str) -> LLMProvider:
    """Get an LLM provider using the tenant's BYOK keys if configured,
    otherwise fall back to the platform default."""
    from argus_agent.api.llm_keys import get_tenant_llm_key

    tenant_config = await get_tenant_llm_key(tenant_id)
    if tenant_config and tenant_config.get("api_key"):
        provider_name = tenant_config.get("provider", "openai")
        if provider_name not in _providers:
            _discover_providers()
        if provider_name not in _providers:
            raise ValueError(
                f"Unknown LLM provider: {provider_name}. Available: {list(_providers.keys())}"
            )

        settings = get_settings()
        # Build a temporary LLMConfig with tenant's keys
        from argus_agent.config import LLMConfig

        tenant_llm = LLMConfig(
            provider=provider_name,
            api_key=tenant_config["api_key"],
            model=tenant_config.get("model") or settings.llm.model,
            base_url=tenant_config.get("base_url") or settings.llm.base_url,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
        )
        return _providers[provider_name](tenant_llm)

    # No BYOK config — use platform default
    return get_provider()


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
