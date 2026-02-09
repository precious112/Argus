"""Tests for Argus configuration system."""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from argus_agent.config import Settings, load_config, reset_settings


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


def test_default_settings():
    settings = Settings()
    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 7600
    assert settings.llm.provider == "openai"
    assert settings.storage.data_dir == "/data"
    assert settings.debug is False


def test_storage_paths_auto_populated():
    settings = Settings()
    assert settings.storage.sqlite_path == "/data/argus.db"
    assert settings.storage.duckdb_path == "/data/argus_ts.duckdb"


def test_custom_storage_dir():
    settings = Settings(storage={"data_dir": "/custom/path"})
    assert settings.storage.sqlite_path == "/custom/path/argus.db"
    assert settings.storage.duckdb_path == "/custom/path/argus_ts.duckdb"


def test_load_from_yaml():
    config = {
        "server": {"port": 8080},
        "llm": {"provider": "anthropic", "model": "claude-3-opus"},
        "debug": True,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        f.flush()
        settings = load_config(f.name)

    os.unlink(f.name)
    assert settings.server.port == 8080
    assert settings.llm.provider == "anthropic"
    assert settings.llm.model == "claude-3-opus"
    assert settings.debug is True


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("ARGUS_DEBUG", "true")
    settings = Settings()
    assert settings.debug is True


def test_host_root_propagation(monkeypatch):
    monkeypatch.setenv("ARGUS_HOST_ROOT", "/host")
    settings = Settings()
    settings.model_post_init(None)
    assert settings.host_root == "/host"
    assert settings.collector.host_root == "/host"
