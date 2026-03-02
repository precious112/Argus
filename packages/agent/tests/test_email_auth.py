"""Tests for email verification, password reset, BYOK LLM, and onboarding logic."""

from __future__ import annotations

import pytest


def test_email_verification_token_model():
    """EmailVerificationToken model should have required fields."""
    from argus_agent.storage.saas_models import EmailVerificationToken

    assert hasattr(EmailVerificationToken, "user_id")
    assert hasattr(EmailVerificationToken, "email")
    assert hasattr(EmailVerificationToken, "token")
    assert hasattr(EmailVerificationToken, "expires_at")
    assert hasattr(EmailVerificationToken, "used_at")


def test_password_reset_token_model():
    """PasswordResetToken model should have required fields."""
    from argus_agent.storage.saas_models import PasswordResetToken

    assert hasattr(PasswordResetToken, "user_id")
    assert hasattr(PasswordResetToken, "token")
    assert hasattr(PasswordResetToken, "expires_at")
    assert hasattr(PasswordResetToken, "used_at")


def test_tenant_llm_config_model():
    """TenantLLMConfig model should have required fields."""
    from argus_agent.storage.saas_models import TenantLLMConfig

    assert hasattr(TenantLLMConfig, "tenant_id")
    assert hasattr(TenantLLMConfig, "provider")
    assert hasattr(TenantLLMConfig, "encrypted_api_key")
    assert hasattr(TenantLLMConfig, "model")
    assert hasattr(TenantLLMConfig, "base_url")


def test_user_model_has_oauth_fields():
    """User model should have OAuth and email_verified fields."""
    from argus_agent.storage.models import User

    assert hasattr(User, "email_verified")
    assert hasattr(User, "oauth_provider")
    assert hasattr(User, "oauth_id")


def test_auth_router_has_password_reset_routes():
    """Auth router should have forgot-password and reset-password."""
    from argus_agent.api.auth import router

    paths = [r.path for r in router.routes]
    assert "/auth/forgot-password" in paths
    assert "/auth/reset-password" in paths
    assert "/auth/verify-email" in paths
    assert "/auth/resend-verification" in paths


def test_llm_key_encryption_roundtrip():
    """Encrypt and decrypt should roundtrip correctly."""
    from argus_agent.api.llm_keys import _decrypt, _derive_key, _encrypt

    key = _derive_key("test-secret", "tenant-123")
    plaintext = "sk-abcdef123456"

    encrypted = _encrypt(plaintext, key)
    assert encrypted != plaintext
    assert encrypted != ""

    decrypted = _decrypt(encrypted, key)
    assert decrypted == plaintext


def test_llm_key_encryption_empty_string():
    """Empty strings should encrypt/decrypt to empty."""
    from argus_agent.api.llm_keys import _decrypt, _derive_key, _encrypt

    key = _derive_key("test-secret", "tenant-123")
    assert _encrypt("", key) == ""
    assert _decrypt("", key) == ""


def test_llm_key_different_tenants_different_keys():
    """Different tenants should produce different encryption keys."""
    from argus_agent.api.llm_keys import _derive_key, _encrypt

    key1 = _derive_key("test-secret", "tenant-1")
    key2 = _derive_key("test-secret", "tenant-2")

    plaintext = "sk-abcdef123456"
    enc1 = _encrypt(plaintext, key1)
    enc2 = _encrypt(plaintext, key2)

    assert enc1 != enc2


@pytest.mark.asyncio
async def test_verify_email_rejects_missing_token():
    """Verify email with invalid token should raise 400."""
    from unittest.mock import AsyncMock, patch

    from fastapi import HTTPException

    from argus_agent.api.auth import VerifyEmailRequest, verify_email
    from argus_agent.config import Settings

    settings = Settings()
    settings.deployment.mode = "saas"

    mock_verify = AsyncMock(return_value={"ok": False, "error": "Invalid token"})

    with (
        patch("argus_agent.api.auth.get_settings", return_value=settings),
        patch("argus_agent.auth.email.verify_email_token", mock_verify),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_email(VerifyEmailRequest(token="bad-token"))
        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_forgot_password_always_returns_ok():
    """Forgot password should return 200 regardless of email existence."""
    from unittest.mock import AsyncMock, patch

    from argus_agent.api.auth import ForgotPasswordRequest, forgot_password
    from argus_agent.config import Settings

    settings = Settings()
    settings.deployment.mode = "saas"

    mock_send = AsyncMock(return_value=True)

    with (
        patch("argus_agent.api.auth.get_settings", return_value=settings),
        patch("argus_agent.auth.email.send_password_reset_email", mock_send),
    ):
        result = await forgot_password(
            ForgotPasswordRequest(email="test@example.com")
        )
        assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_reset_password_rejects_short_password():
    """Reset password should reject passwords under 8 characters."""
    from unittest.mock import patch

    from fastapi import HTTPException

    from argus_agent.api.auth import ResetPasswordRequest, reset_password
    from argus_agent.config import Settings

    settings = Settings()
    settings.deployment.mode = "saas"

    with patch("argus_agent.api.auth.get_settings", return_value=settings):
        with pytest.raises(HTTPException) as exc_info:
            await reset_password(
                ResetPasswordRequest(token="tok", new_password="short")
            )
        assert exc_info.value.status_code == 400


def test_onboarding_router_has_routes():
    """Onboarding router should have status and dismiss routes."""
    from argus_agent.api.onboarding import router

    paths = [r.path for r in router.routes]
    assert "/onboarding/status" in paths
    assert "/onboarding/dismiss" in paths


def test_llm_keys_router_has_routes():
    """LLM keys router should have GET, PUT, DELETE routes."""
    from argus_agent.api.llm_keys import router

    methods = set()
    for route in router.routes:
        if hasattr(route, "methods"):
            methods.update(route.methods)
    assert "GET" in methods
    assert "PUT" in methods
    assert "DELETE" in methods


def test_deployment_config_has_oauth_fields():
    """DeploymentConfig should have OAuth provider fields."""
    from argus_agent.config import DeploymentConfig

    cfg = DeploymentConfig()
    assert cfg.google_client_id == ""
    assert cfg.google_client_secret == ""
    assert cfg.github_client_id == ""
    assert cfg.github_client_secret == ""
