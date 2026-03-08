"""Tests for global user identity — one User per person, TeamMember for org links."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from argus_agent.auth.jwt import create_access_token
from argus_agent.auth.password import hash_password
from argus_agent.config import reset_settings
from argus_agent.storage.models import User
from argus_agent.storage.saas_models import TeamInvitation, TeamMember, Tenant

_AUTH_MOD = "argus_agent.api.auth"
_TEAM_MOD = "argus_agent.api.team"


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    *,
    user_id: str = "",
    tenant_id: str = "t1",
    username: str = "alice",
    email: str = "alice@example.com",
    password: str = "secret123",
    is_active: bool = True,
) -> User:
    u = User(
        id=user_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        username=username,
        email=email,
        password_hash=hash_password(password),
        is_active=is_active,
    )
    return u


def _make_team_member(user_id: str, tenant_id: str, role: str = "owner") -> TeamMember:
    return TeamMember(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
    )


def _make_tenant(tenant_id: str, name: str = "Acme Corp") -> Tenant:
    return Tenant(id=tenant_id, name=name, slug=f"acme-{uuid.uuid4().hex[:8]}")


def _make_invitation(
    tenant_id: str,
    email: str,
    token: str = "test-token",
    role: str = "member",
) -> TeamInvitation:
    return TeamInvitation(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=email,
        role=role,
        invited_by="inviter",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
    )


# ---------------------------------------------------------------------------
# create-org endpoint
# ---------------------------------------------------------------------------

class TestCreateOrg:
    """POST /auth/create-org — create a new org for the current user."""

    @pytest.mark.asyncio
    async def test_creates_org_and_membership(self):
        """Should create Tenant + TeamMember, no new User."""
        from fastapi import FastAPI

        from argus_agent.api.auth import router as auth_router

        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")

        user_id = str(uuid.uuid4())
        token = create_access_token(user_id, "alice", "t1", "owner")

        added_objects = []

        mock_session = AsyncMock()
        mock_session.add = lambda obj: added_objects.append(obj)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(f"{_AUTH_MOD}.get_settings") as ms,
            patch(f"{_AUTH_MOD}._get_raw_session", return_value=mock_session),
        ):
            ms.return_value.deployment.mode = "saas"
            ms.return_value.security.session_expiry_hours = 24

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={"argus_token": token},
            ) as client:
                res = await client.post(
                    "/api/v1/auth/create-org",
                    json={"org_name": "NewCo"},
                )

        assert res.status_code == 200
        data = res.json()
        assert data["tenant_name"] == "NewCo"
        assert data["tenant_id"]

        # Should have added Tenant + TeamMember but NOT a User
        types = {type(o).__name__ for o in added_objects}
        assert "Tenant" in types
        assert "TeamMember" in types
        assert "User" not in types

        # TeamMember should reference the existing user_id
        tm = [o for o in added_objects if isinstance(o, TeamMember)][0]
        assert tm.user_id == user_id
        assert tm.role == "owner"

    @pytest.mark.asyncio
    async def test_create_org_rejects_self_hosted(self):
        """Should return 400 in self-hosted mode."""
        from fastapi import FastAPI

        from argus_agent.api.auth import router as auth_router

        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")

        token = create_access_token("u1", "alice", "default", "member")

        with patch(f"{_AUTH_MOD}.get_settings") as ms:
            ms.return_value.deployment.mode = "self_hosted"
            ms.return_value.security.session_expiry_hours = 24

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={"argus_token": token},
            ) as client:
                res = await client.post(
                    "/api/v1/auth/create-org",
                    json={"org_name": "NewCo"},
                )

        assert res.status_code == 400


# ---------------------------------------------------------------------------
# list-organizations (simplified)
# ---------------------------------------------------------------------------

class TestListOrganizations:
    """GET /auth/organizations — now queries by user_id via TeamMember."""

    @pytest.mark.asyncio
    async def test_returns_all_orgs_for_user(self):
        from fastapi import FastAPI

        from argus_agent.api.auth import router as auth_router

        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")

        user_id = str(uuid.uuid4())
        token = create_access_token(user_id, "alice", "t1", "owner")

        t1 = _make_tenant("t1", "Acme")
        t2 = _make_tenant("t2", "Globex")
        tm1 = _make_team_member(user_id, "t1", "owner")
        tm2 = _make_team_member(user_id, "t2", "member")

        mock_result = MagicMock()
        mock_result.all.return_value = [(tm1, t1), (tm2, t2)]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(f"{_AUTH_MOD}.get_settings") as ms,
            patch(f"{_AUTH_MOD}._get_raw_session", return_value=mock_session),
        ):
            ms.return_value.deployment.mode = "saas"
            ms.return_value.security.session_expiry_hours = 24

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={"argus_token": token},
            ) as client:
                res = await client.get("/api/v1/auth/organizations")

        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2
        names = {o["tenant_name"] for o in data}
        assert names == {"Acme", "Globex"}
        # t1 is current
        current = [o for o in data if o["is_current"]]
        assert len(current) == 1
        assert current[0]["tenant_id"] == "t1"


# ---------------------------------------------------------------------------
# switch-org (simplified)
# ---------------------------------------------------------------------------

class TestSwitchOrg:
    """POST /auth/switch-org — uses same user_id, just verifies TeamMember."""

    @pytest.mark.asyncio
    async def test_switch_issues_new_jwt(self):
        from fastapi import FastAPI

        from argus_agent.api.auth import router as auth_router

        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")

        user_id = str(uuid.uuid4())
        token = create_access_token(user_id, "alice", "t1", "owner")

        tm = _make_team_member(user_id, "t2", "admin")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tm

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(f"{_AUTH_MOD}.get_settings") as ms,
            patch(f"{_AUTH_MOD}._get_raw_session", return_value=mock_session),
        ):
            ms.return_value.deployment.mode = "saas"
            ms.return_value.security.session_expiry_hours = 24

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={"argus_token": token},
            ) as client:
                res = await client.post(
                    "/api/v1/auth/switch-org",
                    json={"tenant_id": "t2"},
                )

        assert res.status_code == 200
        # Should have set a new cookie
        assert "argus_token" in res.cookies

    @pytest.mark.asyncio
    async def test_switch_rejects_non_member(self):
        from fastapi import FastAPI

        from argus_agent.api.auth import router as auth_router

        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")

        user_id = str(uuid.uuid4())
        token = create_access_token(user_id, "alice", "t1", "owner")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(f"{_AUTH_MOD}.get_settings") as ms,
            patch(f"{_AUTH_MOD}._get_raw_session", return_value=mock_session),
        ):
            ms.return_value.deployment.mode = "saas"
            ms.return_value.security.session_expiry_hours = 24

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={"argus_token": token},
            ) as client:
                res = await client.post(
                    "/api/v1/auth/switch-org",
                    json={"tenant_id": "t-nonexistent"},
                )

        assert res.status_code == 403


# ---------------------------------------------------------------------------
# accept-invite with existing user
# ---------------------------------------------------------------------------

class TestAcceptInviteExistingUser:
    """POST /auth/accept-invite — reuses existing User when email matches."""

    @pytest.mark.asyncio
    async def test_validate_returns_has_account(self):
        """GET /auth/accept-invite/validate returns has_account flag."""
        from fastapi import FastAPI

        from argus_agent.api.team import accept_router

        app = FastAPI()
        app.include_router(accept_router, prefix="/api/v1")

        raw_token = "test-validate-token"
        invitation = _make_invitation("t1", "alice@example.com", raw_token)

        # Mock raw session that handles both invitation + user lookup
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invitation

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = "some-user-id"

        mock_raw = AsyncMock()
        mock_raw.execute = AsyncMock(
            side_effect=[inv_result, user_result],
        )
        mock_raw.__aenter__ = AsyncMock(return_value=mock_raw)
        mock_raw.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(f"{_TEAM_MOD}.get_settings") as ms,
            patch("argus_agent.storage.postgres_operational._engine", MagicMock()),
            patch("sqlalchemy.ext.asyncio.AsyncSession", return_value=mock_raw),
        ):
            ms.return_value.deployment.mode = "saas"

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.get(
                    f"/api/v1/auth/accept-invite/validate?token={raw_token}",
                )

        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "alice@example.com"
        assert data["has_account"] is True


# ---------------------------------------------------------------------------
# User model constraints
# ---------------------------------------------------------------------------

class TestUserModelConstraints:
    """Verify User model now has global unique constraints."""

    def test_unique_username_constraint(self):
        """Should have UniqueConstraint on username (not tenant_id+username)."""
        from argus_agent.storage.models import User

        constraints = User.__table_args__
        # Should be a tuple with constraints + dict
        constraint_names = {
            c.name for c in constraints if hasattr(c, "name")
        }
        assert "uq_user_username" in constraint_names
        assert "uq_user_tenant_username" not in constraint_names

    def test_unique_email_constraint(self):
        """Should have UniqueConstraint on email."""
        from argus_agent.storage.models import User

        constraints = User.__table_args__
        constraint_names = {
            c.name for c in constraints if hasattr(c, "name")
        }
        assert "uq_user_email" in constraint_names
