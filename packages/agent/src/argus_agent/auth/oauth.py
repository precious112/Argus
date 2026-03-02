"""OAuth 2.0 authentication for Google and GitHub."""

from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from argus_agent.auth.jwt import create_access_token
from argus_agent.config import get_settings
from argus_agent.storage.models import User
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import TeamMember, Tenant

logger = logging.getLogger("argus.auth.oauth")

router = APIRouter(prefix="/auth/oauth", tags=["auth"])

# ---- Google OAuth ----

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# ---- GitHub OAuth ----

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


@router.get("/providers")
async def oauth_providers() -> dict:
    """Return which OAuth providers are configured."""
    settings = get_settings()
    return {
        "google": bool(settings.deployment.google_client_id),
        "github": bool(settings.deployment.github_client_id),
    }


@router.get("/google/authorize")
async def google_authorize() -> dict:
    """Return the Google OAuth authorization URL."""
    settings = get_settings()
    if not settings.deployment.google_client_id:
        raise HTTPException(400, "Google OAuth not configured")

    redirect_uri = f"{settings.deployment.frontend_url}/login/callback/google"
    params = {
        "client_id": settings.deployment.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = f"{GOOGLE_AUTH_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    return {"url": url}


@router.post("/google/callback")
async def google_callback(body: dict, response: Response):
    """Exchange Google auth code for user info and log in / register."""
    settings = get_settings()
    if not settings.deployment.google_client_id:
        raise HTTPException(400, "Google OAuth not configured")

    code = body.get("code", "")
    if not code:
        raise HTTPException(400, "Missing authorization code")

    redirect_uri = f"{settings.deployment.frontend_url}/login/callback/google"

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": settings.deployment.google_client_id,
            "client_secret": settings.deployment.google_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        })
        if token_resp.status_code != 200:
            logger.warning("Google token exchange failed: %s", token_resp.text)
            raise HTTPException(400, "Failed to exchange authorization code")

        tokens = token_resp.json()
        access_token = tokens.get("access_token", "")

        # Fetch user info
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch user info from Google")

        userinfo = userinfo_resp.json()

    oauth_id = userinfo.get("id", "")
    email = userinfo.get("email", "")
    name = userinfo.get("name", "") or email.split("@")[0]

    if not oauth_id or not email:
        raise HTTPException(400, "Missing user info from Google")

    return await _oauth_login_or_register(
        provider="google",
        oauth_id=oauth_id,
        email=email,
        display_name=name,
        response=response,
    )


@router.get("/github/authorize")
async def github_authorize() -> dict:
    """Return the GitHub OAuth authorization URL."""
    settings = get_settings()
    if not settings.deployment.github_client_id:
        raise HTTPException(400, "GitHub OAuth not configured")

    redirect_uri = f"{settings.deployment.frontend_url}/login/callback/github"
    params = {
        "client_id": settings.deployment.github_client_id,
        "redirect_uri": redirect_uri,
        "scope": "user:email",
    }
    url = f"{GITHUB_AUTH_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    return {"url": url}


@router.post("/github/callback")
async def github_callback(body: dict, response: Response):
    """Exchange GitHub auth code for user info and log in / register."""
    settings = get_settings()
    if not settings.deployment.github_client_id:
        raise HTTPException(400, "GitHub OAuth not configured")

    code = body.get("code", "")
    if not code:
        raise HTTPException(400, "Missing authorization code")

    redirect_uri = f"{settings.deployment.frontend_url}/login/callback/github"

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.deployment.github_client_id,
                "client_secret": settings.deployment.github_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            logger.warning("GitHub token exchange failed: %s", token_resp.text)
            raise HTTPException(400, "Failed to exchange authorization code")

        tokens = token_resp.json()
        access_token = tokens.get("access_token", "")
        if not access_token:
            raise HTTPException(400, "No access token from GitHub")

        # Fetch user info
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        user_resp = await client.get(GITHUB_USER_URL, headers=headers)
        if user_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch user info from GitHub")
        gh_user = user_resp.json()

        # Fetch primary email
        email = gh_user.get("email") or ""
        if not email:
            emails_resp = await client.get(GITHUB_EMAILS_URL, headers=headers)
            if emails_resp.status_code == 200:
                for em in emails_resp.json():
                    if em.get("primary") and em.get("verified"):
                        email = em["email"]
                        break

    oauth_id = str(gh_user.get("id", ""))
    name = gh_user.get("login", "") or email.split("@")[0]

    if not oauth_id or not email:
        raise HTTPException(400, "Missing user info from GitHub")

    return await _oauth_login_or_register(
        provider="github",
        oauth_id=oauth_id,
        email=email,
        display_name=name,
        response=response,
    )


async def _oauth_login_or_register(
    *,
    provider: str,
    oauth_id: str,
    email: str,
    display_name: str,
    response: Response,
) -> Response:
    """Find existing user or create new one, then issue JWT cookie."""
    settings = get_settings()

    async with get_session() as session:
        # 1. Check for existing OAuth user
        result = await session.execute(
            select(User).where(
                User.oauth_provider == provider,
                User.oauth_id == oauth_id,
                User.is_active.is_(True),
            )
        )
        user = result.scalar_one_or_none()

        if user:
            # Existing user — get tenant info and log in
            tm = await session.execute(
                select(TeamMember).where(TeamMember.user_id == user.id)
            )
            member = tm.scalar_one_or_none()
            tenant_id = member.tenant_id if member else "default"
            role = member.role if member else "member"

            token = create_access_token(user.id, user.username, tenant_id, role)
            resp = Response(
                content='{"status":"ok","action":"login"}',
                media_type="application/json",
            )
            resp.set_cookie(
                key="argus_token",
                value=token,
                httponly=True,
                samesite="lax",
                path="/",
                max_age=settings.security.session_expiry_hours * 3600,
            )
            return resp

        # 2. Check if email is already registered (link accounts)
        result = await session.execute(
            select(User).where(User.email == email, User.is_active.is_(True))
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            # Link OAuth to existing account
            existing_user.oauth_provider = provider
            existing_user.oauth_id = oauth_id
            existing_user.email_verified = True
            await session.commit()

            tm = await session.execute(
                select(TeamMember).where(TeamMember.user_id == existing_user.id)
            )
            member = tm.scalar_one_or_none()
            tenant_id = member.tenant_id if member else "default"
            role = member.role if member else "member"

            token = create_access_token(existing_user.id, existing_user.username, tenant_id, role)
            resp = Response(
                content='{"status":"ok","action":"linked"}',
                media_type="application/json",
            )
            resp.set_cookie(
                key="argus_token",
                value=token,
                httponly=True,
                samesite="lax",
                path="/",
                max_age=settings.security.session_expiry_hours * 3600,
            )
            return resp

        # 3. New user — create tenant + user + team member
        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        slug = f"{display_name.lower().replace(' ', '-')[:50]}-{uuid.uuid4().hex[:8]}"

        tenant = Tenant(id=tenant_id, name=f"{display_name}'s Org", slug=slug)
        session.add(tenant)

        user = User(
            id=user_id,
            tenant_id=tenant_id,
            username=display_name,
            email=email,
            password_hash="",
            email_verified=True,  # OAuth emails are pre-verified
            oauth_provider=provider,
            oauth_id=oauth_id,
        )
        session.add(user)

        member = TeamMember(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            role="owner",
        )
        session.add(member)

        await session.commit()

    token = create_access_token(user_id, display_name, tenant_id, "owner")
    resp = Response(
        content='{"status":"ok","action":"registered"}',
        media_type="application/json",
    )
    resp.set_cookie(
        key="argus_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=settings.security.session_expiry_hours * 3600,
    )
    logger.info("OAuth %s user %s registered as tenant %s", provider, display_name, tenant_id)
    return resp
