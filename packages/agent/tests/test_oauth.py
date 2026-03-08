"""Tests for OAuth module."""

from __future__ import annotations

import pytest

from argus_agent.auth.oauth import (
    GITHUB_AUTH_URL,
    GOOGLE_AUTH_URL,
    router,
)


def test_oauth_router_has_expected_routes():
    """OAuth router should have provider, authorize, and callback routes."""
    paths = [r.path for r in router.routes]
    assert "/auth/oauth/providers" in paths
    assert "/auth/oauth/google/authorize" in paths
    assert "/auth/oauth/google/callback" in paths
    assert "/auth/oauth/github/authorize" in paths
    assert "/auth/oauth/github/callback" in paths


def test_google_auth_url_is_correct():
    """Google auth URL should point to accounts.google.com."""
    assert "accounts.google.com" in GOOGLE_AUTH_URL


def test_github_auth_url_is_correct():
    """GitHub auth URL should point to github.com."""
    assert "github.com" in GITHUB_AUTH_URL


@pytest.mark.asyncio
async def test_oauth_providers_endpoint():
    """The /providers endpoint should return boolean flags."""
    from unittest.mock import patch

    from argus_agent.config import Settings

    settings = Settings()
    settings.deployment.mode = "saas"
    settings.deployment.google_client_id = "test-google-id"
    settings.deployment.github_client_id = ""

    with patch("argus_agent.auth.oauth.get_settings", return_value=settings):
        from argus_agent.auth.oauth import oauth_providers

        result = await oauth_providers()

    assert result["google"] is True
    assert result["github"] is False
