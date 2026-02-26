"""Argus configuration system using pydantic-settings with YAML support."""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseModel):
    """HTTP/WebSocket server settings."""

    host: str = "0.0.0.0"
    port: int = 7600
    workers: int = 1


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str | None = None
    temperature: float = 0.1
    max_tokens: int = 4096


class AIBudgetConfig(BaseModel):
    """AI token budget for background tasks."""

    daily_token_limit: int = 5_000_000
    hourly_token_limit: int = 500_000
    review_frequency: str = "6h"
    digest_frequency: str = "24h"
    priority_reserve: float = 0.3


class StorageConfig(BaseModel):
    """Database storage paths."""

    data_dir: str = "/data"
    sqlite_path: str = ""
    duckdb_path: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.sqlite_path:
            self.sqlite_path = str(Path(self.data_dir) / "argus.db")
        if not self.duckdb_path:
            self.duckdb_path = str(Path(self.data_dir) / "argus_ts.duckdb")


class CollectorConfig(BaseModel):
    """Background collector settings."""

    metrics_interval: int = 15
    process_interval: int = 30
    log_paths: list[str] = Field(default_factory=lambda: ["/var/log/syslog", "/var/log/auth.log"])
    host_root: str = ""


class SecurityConfig(BaseModel):
    """Security and authentication settings."""

    secret_key: str = "change-me-on-first-run"
    session_expiry_hours: int = 24
    max_login_attempts: int = 10
    lockout_minutes: int = 15


class LicenseConfig(BaseModel):
    """License key configuration for open-core feature gating."""

    key: str = ""


class AlertConfig(BaseModel):
    """Alerting configuration."""

    webhook_urls: list[str] = Field(default_factory=list)
    email_enabled: bool = False
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_from: str = ""
    email_to: list[str] = Field(default_factory=list)
    batch_window: int = 90
    min_external_severity: str = "NOTABLE"
    ai_enhance: bool = False


class Settings(BaseSettings):
    """Root configuration for Argus agent."""

    model_config = SettingsConfigDict(
        env_prefix="ARGUS_",
        env_nested_delimiter="__",
    )

    mode: str = Field(default="full", description="Operating mode: 'full' or 'sdk_only'")
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    ai_budget: AIBudgetConfig = Field(default_factory=AIBudgetConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    alerting: AlertConfig = Field(default_factory=AlertConfig)
    license: LicenseConfig = Field(default_factory=LicenseConfig)

    debug: bool = False
    host_root: str = ""

    def model_post_init(self, __context: Any) -> None:
        host_root = os.environ.get("ARGUS_HOST_ROOT", self.host_root)
        if host_root:
            self.host_root = host_root
            self.collector.host_root = host_root


def load_config(config_path: str | Path | None = None) -> Settings:
    """Load configuration from YAML file and environment variables.

    Environment variables override YAML values. YAML overrides defaults.
    """
    yaml_data: dict[str, Any] = {}

    if config_path is None:
        candidates = [
            Path("argus.yaml"),
            Path("argus.yml"),
            Path("/etc/argus/argus.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                yaml_data = yaml.safe_load(f) or {}

    return Settings(**yaml_data)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = load_config()
    return _settings


def reset_settings() -> None:
    """Reset settings singleton (for testing)."""
    global _settings
    _settings = None


_DEFAULT_SECRET = "change-me-on-first-run"
_logger = logging.getLogger("argus")


def ensure_secret_key(settings: Settings) -> None:
    """Auto-generate a JWT secret key on first run if the user hasn't set one.

    The generated key is persisted to ``{data_dir}/.secret_key`` so it
    survives restarts.  Users who explicitly set ``ARGUS_SECURITY__SECRET_KEY``
    or provide a value in ``argus.yaml`` keep full control.
    """
    if settings.security.secret_key != _DEFAULT_SECRET:
        return  # user provided their own key

    secret_file = Path(settings.storage.data_dir) / ".secret_key"

    if secret_file.exists():
        settings.security.secret_key = secret_file.read_text().strip()
        _logger.info("Loaded secret key from %s", secret_file)
    else:
        key = secrets.token_urlsafe(32)
        secret_file.write_text(key)
        secret_file.chmod(0o600)
        settings.security.secret_key = key
        _logger.info("Generated new secret key and saved to %s", secret_file)
