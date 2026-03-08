"""Slack OAuth V2 service — authorize, token exchange, disconnect, channels."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import uuid
from urllib.parse import urlencode

import httpx
from sqlalchemy import select

from argus_agent.config import get_settings
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import SlackInstallation

logger = logging.getLogger("argus.integrations.slack")

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_AUTH_TEST_URL = "https://slack.com/api/auth.test"
SLACK_CONVERSATIONS_LIST_URL = "https://slack.com/api/conversations.list"
SLACK_CHAT_POST_URL = "https://slack.com/api/chat.postMessage"

BOT_SCOPES = "chat:write,channels:read,groups:read"


# ---------- Encryption (reuses pattern from api/llm_keys.py) ----------

def _derive_key(secret: str, tenant_id: str) -> bytes:
    """Derive a tenant-specific encryption key from the server secret."""
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), tenant_id.encode(), 100_000)


def _encrypt(plaintext: str, key: bytes) -> str:
    if not plaintext:
        return ""
    pt_bytes = plaintext.encode()
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(pt_bytes))
    return base64.b64encode(encrypted).decode()


def _decrypt(ciphertext: str, key: bytes) -> str:
    if not ciphertext:
        return ""
    ct_bytes = base64.b64decode(ciphertext)
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(ct_bytes))
    return decrypted.decode()


# ---------- State HMAC ----------

def _make_state(tenant_id: str, user_id: str) -> str:
    """Build an HMAC-signed state parameter: base64(tenant_id:user_id:hmac)."""
    settings = get_settings()
    payload = f"{tenant_id}:{user_id}"
    sig = hmac.new(
        settings.security.secret_key.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _verify_state(state: str) -> tuple[str, str]:
    """Verify and extract (tenant_id, user_id) from the state param.

    Raises ValueError on invalid/tampered state.
    """
    settings = get_settings()
    try:
        raw = base64.urlsafe_b64decode(state.encode()).decode()
    except Exception as exc:
        raise ValueError("Invalid state encoding") from exc

    parts = raw.split(":")
    if len(parts) != 3:
        raise ValueError("Malformed state")

    tenant_id, user_id, sig = parts
    payload = f"{tenant_id}:{user_id}"
    expected = hmac.new(
        settings.security.secret_key.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(sig, expected):
        raise ValueError("State signature mismatch")

    return tenant_id, user_id


# ---------- OAuth flow ----------

def get_authorize_url(tenant_id: str, user_id: str) -> str:
    """Build the Slack OAuth V2 authorize URL."""
    settings = get_settings()
    state = _make_state(tenant_id, user_id)
    params = {
        "client_id": settings.deployment.slack_client_id,
        "scope": BOT_SCOPES,
        "redirect_uri": f"{settings.deployment.api_base_url or settings.deployment.frontend_url}/api/v1/integrations/slack/callback",
        "state": state,
    }
    return f"{SLACK_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str, state: str) -> SlackInstallation:
    """Exchange the OAuth code for a bot token and upsert the installation.

    Raises ValueError on invalid state or Slack API error.
    """
    tenant_id, user_id = _verify_state(state)
    settings = get_settings()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            SLACK_TOKEN_URL,
            data={
                "client_id": settings.deployment.slack_client_id,
                "client_secret": settings.deployment.slack_client_secret,
                "code": code,
                "redirect_uri": (
                    f"{settings.deployment.api_base_url or settings.deployment.frontend_url}"
                    "/api/v1/integrations/slack/callback"
                ),
            },
        )
        data = resp.json()

    if not data.get("ok"):
        error = data.get("error", "unknown_error")
        raise ValueError(f"Slack OAuth error: {error}")

    bot_token = data.get("access_token", "")
    team_id = data.get("team", {}).get("id", "")
    team_name = data.get("team", {}).get("name", "")
    bot_user_id = data.get("bot_user_id", "")

    # Encrypt bot token
    enc_key = _derive_key(settings.security.secret_key, tenant_id)
    encrypted_token = _encrypt(bot_token, enc_key)

    # Set tenant context for RLS (callback is auth-exempt, so middleware doesn't set it)
    from argus_agent.tenancy.context import set_tenant_id

    set_tenant_id(tenant_id)

    # Upsert installation
    async with get_session() as session:
        result = await session.execute(
            select(SlackInstallation).where(SlackInstallation.tenant_id == tenant_id)
        )
        install = result.scalar_one_or_none()

        if install:
            install.team_id = team_id
            install.team_name = team_name
            install.bot_token = encrypted_token
            install.bot_user_id = bot_user_id
            install.installed_by = user_id
            install.is_active = True
        else:
            install = SlackInstallation(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                team_id=team_id,
                team_name=team_name,
                bot_token=encrypted_token,
                bot_user_id=bot_user_id,
                installed_by=user_id,
                is_active=True,
            )
            session.add(install)

        await session.commit()
        await session.refresh(install)

    logger.info("Slack installed for tenant %s (workspace %s)", tenant_id, team_name)
    return install


async def disconnect(tenant_id: str) -> None:
    """Disconnect Slack — deactivate and wipe token."""
    async with get_session() as session:
        result = await session.execute(
            select(SlackInstallation).where(
                SlackInstallation.tenant_id == tenant_id,
                SlackInstallation.is_active.is_(True),
            )
        )
        install = result.scalar_one_or_none()
        if install:
            install.is_active = False
            install.bot_token = ""
            await session.commit()
    logger.info("Slack disconnected for tenant %s", tenant_id)


async def get_installation(tenant_id: str) -> SlackInstallation | None:
    """Fetch the active Slack installation for a tenant."""
    async with get_session() as session:
        result = await session.execute(
            select(SlackInstallation).where(
                SlackInstallation.tenant_id == tenant_id,
                SlackInstallation.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()


def decrypt_bot_token(install: SlackInstallation) -> str:
    """Decrypt the stored bot token for a given installation."""
    settings = get_settings()
    enc_key = _derive_key(settings.security.secret_key, install.tenant_id)
    return _decrypt(install.bot_token, enc_key)


async def list_channels(tenant_id: str) -> list[dict]:
    """List Slack channels using the stored bot token."""
    install = await get_installation(tenant_id)
    if not install:
        return []

    bot_token = decrypt_bot_token(install)
    if not bot_token:
        return []

    channels: list[dict] = []
    cursor = None

    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(5):  # max 5 pages
            params: dict[str, str] = {"types": "public_channel,private_channel", "limit": "200"}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                SLACK_CONVERSATIONS_LIST_URL,
                headers={"Authorization": f"Bearer {bot_token}"},
                params=params,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning("Slack conversations.list error: %s", data.get("error"))
                break

            for ch in data.get("channels", []):
                channels.append({
                    "id": ch["id"],
                    "name": ch.get("name", ""),
                    "is_private": ch.get("is_private", False),
                })

            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

    return channels


async def test_connection(tenant_id: str) -> dict:
    """Test the Slack connection — auth.test + send a test message."""
    install = await get_installation(tenant_id)
    if not install:
        return {"ok": False, "error": "not_installed"}

    bot_token = decrypt_bot_token(install)
    if not bot_token:
        return {"ok": False, "error": "no_token"}

    async with httpx.AsyncClient(timeout=15) as client:
        # auth.test
        auth_resp = await client.post(
            SLACK_AUTH_TEST_URL,
            headers={"Authorization": f"Bearer {bot_token}"},
        )
        auth_data = auth_resp.json()
        if not auth_data.get("ok"):
            return {"ok": False, "error": auth_data.get("error", "auth_test_failed")}

        # Send test message if channel is configured
        if install.default_channel_id:
            msg_resp = await client.post(
                SLACK_CHAT_POST_URL,
                headers={"Authorization": f"Bearer {bot_token}"},
                json={
                    "channel": install.default_channel_id,
                    "text": ":white_check_mark: Argus Slack integration is working!",
                },
            )
            msg_data = msg_resp.json()
            if not msg_data.get("ok"):
                return {
                    "ok": False,
                    "error": f"message_send_failed: {msg_data.get('error', '')}",
                }

    return {"ok": True, "team": auth_data.get("team", ""), "user": auth_data.get("user", "")}
