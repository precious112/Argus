"""Tests for NotificationSettingsService."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from argus_agent.alerting.settings import _MASK, NotificationSettingsService
from argus_agent.config import AlertConfig
from argus_agent.storage.models import Base


@pytest.fixture()
async def _init_db(monkeypatch):
    """Create an in-memory SQLite database for tests."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Monkey-patch get_session to use our in-memory DB
    import argus_agent.storage.database as db_mod
    import argus_agent.storage.repositories as repo_mod
    from argus_agent.storage.sqlite_operational import SQLiteOperationalRepository

    monkeypatch.setattr(db_mod, "_session_factory", factory)
    monkeypatch.setattr(repo_mod, "_operational_repo", SQLiteOperationalRepository())

    yield

    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_upsert_and_get_all():
    svc = NotificationSettingsService()
    await svc.upsert("slack", True, {"bot_token": "xoxb-secret", "channel_id": "C123"})

    configs = await svc.get_all()
    assert len(configs) == 1
    assert configs[0]["channel_type"] == "slack"
    assert configs[0]["enabled"] is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_secret_masking():
    svc = NotificationSettingsService()
    await svc.upsert("slack", True, {"bot_token": "xoxb-real-token", "channel_id": "C1"})

    masked = await svc.get_all()
    assert masked[0]["config"]["bot_token"] == _MASK

    raw = await svc.get_all_raw()
    assert raw[0]["config"]["bot_token"] == "xoxb-real-token"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_upsert_preserves_masked_secrets():
    svc = NotificationSettingsService()
    await svc.upsert("slack", True, {"bot_token": "xoxb-original", "channel_id": "C1"})

    # Simulate UI sending back masked token
    await svc.upsert("slack", True, {"bot_token": _MASK, "channel_id": "C2"})

    raw = await svc.get_all_raw()
    assert raw[0]["config"]["bot_token"] == "xoxb-original"
    assert raw[0]["config"]["channel_id"] == "C2"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_get_by_type():
    svc = NotificationSettingsService()
    await svc.upsert("email", False, {"smtp_host": "smtp.example.com"})

    result = await svc.get_by_type("email")
    assert result is not None
    assert result["channel_type"] == "email"

    result = await svc.get_by_type("slack")
    assert result is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_delete():
    svc = NotificationSettingsService()
    await svc.upsert("webhook", True, {"urls": ["https://example.com/hook"]})

    deleted = await svc.delete("webhook")
    assert deleted is True

    deleted = await svc.delete("webhook")
    assert deleted is False

    configs = await svc.get_all()
    assert len(configs) == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_initialize_from_config_seeds():
    svc = NotificationSettingsService()
    alert_cfg = AlertConfig(
        webhook_urls=["https://hooks.slack.com/x"],
        email_enabled=True,
        email_smtp_host="smtp.test.com",
        email_smtp_port=587,
        email_from="a@b.com",
        email_to=["c@d.com"],
    )
    await svc.initialize_from_config(alert_cfg)

    configs = await svc.get_all_raw()
    types = {c["channel_type"] for c in configs}
    assert "webhook" in types
    assert "email" in types


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_initialize_from_config_skips_existing():
    svc = NotificationSettingsService()
    # Pre-create webhook config
    await svc.upsert("webhook", False, {"urls": ["https://existing.com"]})

    alert_cfg = AlertConfig(
        webhook_urls=["https://hooks.slack.com/new"],
    )
    await svc.initialize_from_config(alert_cfg)

    raw = await svc.get_all_raw()
    webhook = [c for c in raw if c["channel_type"] == "webhook"][0]
    assert webhook["config"]["urls"] == ["https://existing.com"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_init_db")
async def test_email_secret_masking():
    svc = NotificationSettingsService()
    await svc.upsert("email", True, {
        "smtp_host": "smtp.test.com",
        "smtp_password": "s3cret",
    })

    masked = await svc.get_all()
    assert masked[0]["config"]["smtp_password"] == _MASK

    raw = await svc.get_all_raw()
    assert raw[0]["config"]["smtp_password"] == "s3cret"
