"""Tests for LLMSettingsService."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from argus_agent.llm.settings import _MASK, LLMSettingsService
from argus_agent.storage.models import Base


@pytest.fixture()
async def _init_db(monkeypatch):
    """Create an in-memory SQLite database for tests."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    import argus_agent.storage.database as db_mod

    monkeypatch.setattr(db_mod, "_session_factory", factory)

    yield

    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_empty_db_returns_empty():
    svc = LLMSettingsService()
    result = await svc.get_all()
    assert result == {}


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_save_and_retrieve():
    svc = LLMSettingsService()
    await svc.save({
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "api_key": "sk-ant-secret",
    })

    raw = await svc.get_raw()
    assert raw["provider"] == "anthropic"
    assert raw["model"] == "claude-sonnet-4-5-20250929"
    assert raw["api_key"] == "sk-ant-secret"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_masked_api_key():
    svc = LLMSettingsService()
    await svc.save({"provider": "openai", "api_key": "sk-real-key"})

    masked = await svc.get_all(masked=True)
    assert masked["api_key"] == _MASK
    assert masked["provider"] == "openai"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_save_preserves_existing_when_masked():
    svc = LLMSettingsService()
    await svc.save({"api_key": "sk-original"})

    # Simulate UI sending back masked key
    await svc.save({"api_key": _MASK})

    raw = await svc.get_raw()
    assert raw["api_key"] == "sk-original"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_partial_update():
    svc = LLMSettingsService()
    await svc.save({"provider": "openai", "model": "gpt-4o", "api_key": "sk-123"})

    # Update only model
    await svc.save({"model": "gpt-4o-mini"})

    raw = await svc.get_raw()
    assert raw["provider"] == "openai"
    assert raw["model"] == "gpt-4o-mini"
    assert raw["api_key"] == "sk-123"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_has_persisted_settings_empty():
    svc = LLMSettingsService()
    assert await svc.has_persisted_settings() is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_has_persisted_settings_after_save():
    svc = LLMSettingsService()
    await svc.save({"provider": "gemini"})
    assert await svc.has_persisted_settings() is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_apply_to_settings_overrides(monkeypatch):
    svc = LLMSettingsService()
    await svc.save({"provider": "anthropic", "model": "claude-opus-4", "api_key": "sk-test"})

    # Set up a fresh Settings singleton
    from argus_agent import config as config_mod
    from argus_agent.config import LLMConfig, Settings

    test_settings = Settings(llm=LLMConfig(provider="openai", model="gpt-4o", api_key="old-key"))
    monkeypatch.setattr(config_mod, "get_settings", lambda: test_settings)

    await svc.apply_to_settings()

    assert test_settings.llm.provider == "anthropic"
    assert test_settings.llm.model == "claude-opus-4"
    assert test_settings.llm.api_key == "sk-test"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_apply_to_settings_noop_when_empty(monkeypatch):
    svc = LLMSettingsService()

    from argus_agent import config as config_mod
    from argus_agent.config import LLMConfig, Settings

    test_settings = Settings(llm=LLMConfig(provider="openai", model="gpt-4o"))
    monkeypatch.setattr(config_mod, "get_settings", lambda: test_settings)

    await svc.apply_to_settings()

    # Should remain unchanged
    assert test_settings.llm.provider == "openai"
    assert test_settings.llm.model == "gpt-4o"
