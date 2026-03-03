"""Tests for Slack OAuth bot integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from argus_agent.auth.dependencies import get_current_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_admin():
    return {"sub": "user-1", "tenant_id": "tenant-1", "role": "admin"}


def _make_app():
    """Create a minimal test app with the Slack integration router."""
    from fastapi import FastAPI

    from argus_agent.api.slack_integration import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _fake_admin()
    return app


@pytest.fixture
def mock_app():
    return _make_app()


def _mock_session_ctx(mock_session):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_install(*, active=True, channel_id="C123", channel_name="alerts"):
    inst = MagicMock()
    inst.tenant_id = "tenant-1"
    inst.team_id = "T123"
    inst.team_name = "TestWorkspace"
    inst.bot_token = "encrypted-token"
    inst.bot_user_id = "U123"
    inst.default_channel_id = channel_id
    inst.default_channel_name = channel_name
    inst.installed_by = "user-1"
    inst.is_active = active
    return inst


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class TestSlackInstallationModel:
    def test_model_fields(self):
        from argus_agent.storage.saas_models import SlackInstallation

        cols = {c.name for c in SlackInstallation.__table__.columns}
        expected = {
            "id", "tenant_id", "team_id", "team_name", "bot_token",
            "bot_user_id", "default_channel_id", "default_channel_name",
            "installed_by", "is_active", "created_at", "updated_at",
        }
        assert expected.issubset(cols)

    def test_unique_tenant_index(self):
        from argus_agent.storage.saas_models import SlackInstallation

        indexes = {idx.name for idx in SlackInstallation.__table__.indexes}
        assert "ix_slack_installations_tenant" in indexes


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestDeploymentConfig:
    def test_slack_fields_exist(self):
        from argus_agent.config import DeploymentConfig

        cfg = DeploymentConfig()
        assert cfg.slack_client_id == ""
        assert cfg.slack_client_secret == ""
        assert cfg.slack_signing_secret == ""


# ---------------------------------------------------------------------------
# State HMAC
# ---------------------------------------------------------------------------


class TestStateHMAC:
    @patch("argus_agent.integrations.slack_oauth.get_settings")
    def test_make_and_verify_state(self, mock_settings):
        mock_settings.return_value = MagicMock(
            security=MagicMock(secret_key="test-secret-key")
        )

        from argus_agent.integrations.slack_oauth import _make_state, _verify_state

        state = _make_state("tenant-1", "user-1")
        tenant_id, user_id = _verify_state(state)
        assert tenant_id == "tenant-1"
        assert user_id == "user-1"

    @patch("argus_agent.integrations.slack_oauth.get_settings")
    def test_invalid_state_rejected(self, mock_settings):
        mock_settings.return_value = MagicMock(
            security=MagicMock(secret_key="test-secret-key")
        )

        from argus_agent.integrations.slack_oauth import _verify_state

        with pytest.raises(ValueError, match="Invalid state"):
            _verify_state("not-base64!!!")

    @patch("argus_agent.integrations.slack_oauth.get_settings")
    def test_tampered_state_rejected(self, mock_settings):
        import base64

        mock_settings.return_value = MagicMock(
            security=MagicMock(secret_key="test-secret-key")
        )

        from argus_agent.integrations.slack_oauth import _verify_state

        tampered = base64.urlsafe_b64encode(b"tenant-1:user-1:badhash").decode()
        with pytest.raises(ValueError, match="signature mismatch"):
            _verify_state(tampered)


# ---------------------------------------------------------------------------
# Authorize URL
# ---------------------------------------------------------------------------


class TestAuthorizeURL:
    @patch("argus_agent.integrations.slack_oauth.get_settings")
    def test_authorize_url_contains_scopes(self, mock_settings):
        mock_settings.return_value = MagicMock(
            security=MagicMock(secret_key="test-secret"),
            deployment=MagicMock(
                slack_client_id="test-client-id",
                frontend_url="http://localhost:3000",
            ),
        )

        from argus_agent.integrations.slack_oauth import get_authorize_url

        url = get_authorize_url("tenant-1", "user-1")
        assert "slack.com/oauth/v2/authorize" in url
        assert "test-client-id" in url
        assert "chat%3Awrite" in url or "chat:write" in url
        assert "state=" in url


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


class TestSlackStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_disconnected(self, mock_app):
        with patch(
            "argus_agent.api.slack_integration.get_installation",
            new_callable=AsyncMock,
            return_value=None,
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.get("/api/v1/integrations/slack/status")
            assert res.status_code == 200
            assert res.json()["connected"] is False

    @pytest.mark.asyncio
    async def test_status_connected(self, mock_app):
        install = _mock_install()
        with patch(
            "argus_agent.api.slack_integration.get_installation",
            new_callable=AsyncMock,
            return_value=install,
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.get("/api/v1/integrations/slack/status")
            assert res.status_code == 200
            data = res.json()
            assert data["connected"] is True
            assert data["team_name"] == "TestWorkspace"
            assert data["channel_name"] == "alerts"


class TestSlackDisconnectEndpoint:
    @pytest.mark.asyncio
    async def test_disconnect(self, mock_app):
        with patch(
            "argus_agent.api.slack_integration.slack_disconnect",
            new_callable=AsyncMock,
        ) as mock_dc:
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post("/api/v1/integrations/slack/disconnect")
            assert res.status_code == 200
            assert res.json()["status"] == "disconnected"
            mock_dc.assert_called_once_with("tenant-1")


class TestSlackTestEndpoint:
    @pytest.mark.asyncio
    async def test_test_ok(self, mock_app):
        with patch(
            "argus_agent.api.slack_integration.slack_test_connection",
            new_callable=AsyncMock,
            return_value={"ok": True, "team": "TestWS", "user": "argus-bot"},
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post("/api/v1/integrations/slack/test")
            assert res.status_code == 200
            assert res.json()["ok"] is True


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------


class TestTokenEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        from argus_agent.integrations.slack_oauth import _decrypt, _derive_key, _encrypt

        key = _derive_key("my-secret", "tenant-1")
        token = "xoxb-1234567890-abcdefghij"
        encrypted = _encrypt(token, key)
        assert encrypted != token
        assert _decrypt(encrypted, key) == token

    def test_empty_string(self):
        from argus_agent.integrations.slack_oauth import _decrypt, _derive_key, _encrypt

        key = _derive_key("my-secret", "tenant-1")
        assert _encrypt("", key) == ""
        assert _decrypt("", key) == ""


# ---------------------------------------------------------------------------
# Exchange Code (mocked Slack API)
# ---------------------------------------------------------------------------


class TestExchangeCode:
    @pytest.mark.asyncio
    async def test_exchange_code_success(self):
        from argus_agent.integrations.slack_oauth import _make_state

        mock_settings = MagicMock(
            security=MagicMock(secret_key="test-secret"),
            deployment=MagicMock(
                slack_client_id="cid",
                slack_client_secret="csecret",
                frontend_url="http://localhost:3000",
            ),
        )

        state = None
        with patch("argus_agent.integrations.slack_oauth.get_settings", return_value=mock_settings):
            state = _make_state("tenant-1", "user-1")

        slack_response = {
            "ok": True,
            "access_token": "xoxb-test-token-123",
            "team": {"id": "T123", "name": "TestTeam"},
            "bot_user_id": "U456",
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = slack_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        with (
            patch("argus_agent.integrations.slack_oauth.get_settings", return_value=mock_settings),
            patch("argus_agent.integrations.slack_oauth.httpx.AsyncClient", return_value=mock_client),
            patch("argus_agent.integrations.slack_oauth.get_session", return_value=_mock_session_ctx(mock_session)),
        ):
            from argus_agent.integrations.slack_oauth import exchange_code

            await exchange_code("test-code", state)

        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_exchange_code_slack_error(self):
        from argus_agent.integrations.slack_oauth import _make_state

        mock_settings = MagicMock(
            security=MagicMock(secret_key="test-secret"),
            deployment=MagicMock(
                slack_client_id="cid",
                slack_client_secret="csecret",
                frontend_url="http://localhost:3000",
            ),
        )

        with patch("argus_agent.integrations.slack_oauth.get_settings", return_value=mock_settings):
            state = _make_state("tenant-1", "user-1")

        slack_response = {"ok": False, "error": "invalid_code"}

        mock_resp = MagicMock()
        mock_resp.json.return_value = slack_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("argus_agent.integrations.slack_oauth.get_settings", return_value=mock_settings),
            patch("argus_agent.integrations.slack_oauth.httpx.AsyncClient", return_value=mock_client),
        ):
            from argus_agent.integrations.slack_oauth import exchange_code

            with pytest.raises(ValueError, match="invalid_code"):
                await exchange_code("bad-code", state)


# ---------------------------------------------------------------------------
# reload_channels with OAuth install
# ---------------------------------------------------------------------------


class TestReloadChannelsOAuth:
    @pytest.mark.asyncio
    async def test_oauth_install_creates_slack_channel(self):
        """When an OAuth Slack installation is active, reload_channels should create a SlackChannel."""
        install = _mock_install(channel_id="C999", channel_name="ops-alerts")

        mock_settings = MagicMock()
        mock_settings.deployment.mode = "saas"
        mock_settings.security.secret_key = "test-key"

        with (
            patch("argus_agent.config.get_settings", return_value=mock_settings),
            patch(
                "argus_agent.integrations.slack_oauth.get_installation",
                new_callable=AsyncMock,
                return_value=install,
            ),
            patch(
                "argus_agent.integrations.slack_oauth.decrypt_bot_token",
                return_value="xoxb-decrypted-token",
            ),
            patch("argus_agent.tenancy.context.get_tenant_id", return_value="tenant-1"),
            patch("argus_agent.main._get_alert_engine") as mock_engine,
            patch("argus_agent.main._get_alert_formatter") as mock_formatter,
            patch("argus_agent.main._get_distributed_manager", return_value=None),
            patch("argus_agent.alerting.reload.NotificationSettingsService") as mock_svc_cls,
            patch("argus_agent.api.ws.manager"),
        ):
            mock_engine_inst = MagicMock()
            mock_engine.return_value = mock_engine_inst

            mock_formatter_inst = MagicMock()
            mock_formatter.return_value = mock_formatter_inst

            mock_svc = AsyncMock()
            mock_svc.get_all_raw.return_value = []
            mock_svc_cls.return_value = mock_svc

            from argus_agent.alerting.reload import reload_channels

            await reload_channels()

            # The formatter should have been called with channels containing a SlackChannel
            if mock_formatter_inst.set_channels.called:
                channels = mock_formatter_inst.set_channels.call_args[0][0]
                slack_channels = [
                    ch for ch in channels
                    if type(ch).__name__ == "SlackChannel"
                ]
                assert len(slack_channels) == 1
