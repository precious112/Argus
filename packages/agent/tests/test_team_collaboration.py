"""Tests for Phase 8: Team Collaboration features."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from argus_agent.auth.dependencies import get_current_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_user():
    return {"sub": "user-1", "tenant_id": "tenant-1", "role": "admin"}


def _make_app():
    """Create a minimal test app with Phase 8 routers."""
    from fastapi import FastAPI

    from argus_agent.api.investigations import router as inv_router
    from argus_agent.api.service_config import (
        escalation_router,
    )
    from argus_agent.api.service_config import (
        router as svc_router,
    )

    app = FastAPI()
    app.include_router(svc_router, prefix="/api/v1")
    app.include_router(escalation_router, prefix="/api/v1")
    app.include_router(inv_router, prefix="/api/v1")
    # Override auth dependency
    app.dependency_overrides[get_current_user] = lambda: _fake_user()
    return app


@pytest.fixture
def mock_app():
    return _make_app()


def _mock_session_ctx(mock_session):
    """Return a mock that works as an async context manager."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Service Config API
# ---------------------------------------------------------------------------


class TestServiceConfigAPI:
    @pytest.mark.asyncio
    async def test_list_configs_empty(self, mock_app):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "argus_agent.api.service_config.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.get("/api/v1/service-configs")
            assert res.status_code == 200
            assert res.json()["configs"] == []

    @pytest.mark.asyncio
    async def test_upsert_config(self, mock_app):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        with patch(
            "argus_agent.api.service_config.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.put(
                    "/api/v1/service-configs/my-service",
                    json={
                        "service_name": "my-service",
                        "environment": "staging",
                        "owner_user_id": "user-1",
                        "description": "Test service",
                    },
                )
            assert res.status_code == 200
            assert res.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_delete_config(self, mock_app):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "argus_agent.api.service_config.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.delete("/api/v1/service-configs/my-service")
            assert res.status_code == 200
            assert res.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Escalation Policy API
# ---------------------------------------------------------------------------


class TestEscalationPolicyAPI:
    @pytest.mark.asyncio
    async def test_list_policies_empty(self, mock_app):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "argus_agent.api.service_config.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.get("/api/v1/escalation-policies")
            assert res.status_code == 200
            assert res.json()["policies"] == []

    @pytest.mark.asyncio
    async def test_create_policy(self, mock_app):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        with patch(
            "argus_agent.api.service_config.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.post(
                    "/api/v1/escalation-policies",
                    json={
                        "name": "Critical Alerts",
                        "service_name": "api-gateway",
                        "min_severity": "CRITICAL",
                        "primary_contact_id": "user-1",
                        "backup_contact_id": "user-2",
                    },
                )
            assert res.status_code == 200
            assert res.json()["status"] == "ok"
            assert "id" in res.json()

    @pytest.mark.asyncio
    async def test_update_policy(self, mock_app):
        mock_policy = MagicMock()
        mock_policy.id = "pol-1"
        mock_policy.tenant_id = "tenant-1"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_policy
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch(
            "argus_agent.api.service_config.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.put(
                    "/api/v1/escalation-policies/pol-1",
                    json={"name": "Updated Policy", "min_severity": "URGENT"},
                )
            assert res.status_code == 200
            assert mock_policy.name == "Updated Policy"
            assert mock_policy.min_severity == "URGENT"

    @pytest.mark.asyncio
    async def test_update_policy_not_found(self, mock_app):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "argus_agent.api.service_config.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.put(
                    "/api/v1/escalation-policies/nonexistent",
                    json={"name": "X"},
                )
            assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_policy(self, mock_app):
        mock_policy = MagicMock()
        mock_policy.is_active = True

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_policy
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch(
            "argus_agent.api.service_config.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.delete("/api/v1/escalation-policies/pol-1")
            assert res.status_code == 200
            assert res.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Investigations API
# ---------------------------------------------------------------------------


class TestInvestigationsAPI:
    @pytest.mark.asyncio
    async def test_list_investigations_empty(self, mock_app):
        mock_session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        with patch(
            "argus_agent.api.investigations.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.get("/api/v1/investigations")
            assert res.status_code == 200
            data = res.json()
            assert data["investigations"] == []
            assert data["total"] == 0
            assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_assign_investigation(self, mock_app):
        mock_inv = MagicMock()
        mock_inv.id = "inv-1"
        mock_inv.tenant_id = "tenant-1"
        mock_inv.assigned_to = ""
        mock_inv.assigned_by = ""

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_inv
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch(
            "argus_agent.api.investigations.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.post(
                    "/api/v1/investigations/inv-1/assign",
                    json={"assigned_to": "user-2"},
                )
            assert res.status_code == 200
            assert mock_inv.assigned_to == "user-2"
            assert mock_inv.assigned_by == "user-1"

    @pytest.mark.asyncio
    async def test_assign_investigation_not_found(self, mock_app):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "argus_agent.api.investigations.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.post(
                    "/api/v1/investigations/nonexistent/assign",
                    json={"assigned_to": "user-2"},
                )
            assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_unassign_investigation(self, mock_app):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "argus_agent.api.investigations.get_session",
            return_value=_mock_session_ctx(mock_session),
        ):
            transport = ASGITransport(app=mock_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                res = await client.post("/api/v1/investigations/inv-1/unassign")
            assert res.status_code == 200
            assert res.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_service_config_model_fields(self):
        from argus_agent.storage.saas_models import ServiceConfig

        assert hasattr(ServiceConfig, "id")
        assert hasattr(ServiceConfig, "tenant_id")
        assert hasattr(ServiceConfig, "service_name")
        assert hasattr(ServiceConfig, "environment")
        assert hasattr(ServiceConfig, "owner_user_id")
        assert ServiceConfig.__tablename__ == "service_configs"

    def test_escalation_policy_model_fields(self):
        from argus_agent.storage.saas_models import EscalationPolicy

        assert hasattr(EscalationPolicy, "id")
        assert hasattr(EscalationPolicy, "tenant_id")
        assert hasattr(EscalationPolicy, "name")
        assert hasattr(EscalationPolicy, "primary_contact_id")
        assert hasattr(EscalationPolicy, "backup_contact_id")
        assert hasattr(EscalationPolicy, "is_active")
        assert EscalationPolicy.__tablename__ == "escalation_policies"

    def test_investigation_assignment_fields(self):
        from argus_agent.storage.models import Investigation

        assert hasattr(Investigation, "assigned_to")
        assert hasattr(Investigation, "assigned_by")
        assert hasattr(Investigation, "service_name")


# ---------------------------------------------------------------------------
# Router Registration
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    def test_service_config_routes(self):
        from argus_agent.api.service_config import router

        paths = [r.path for r in router.routes]
        assert "/service-configs" in paths
        assert "/service-configs/{service_name}" in paths

    def test_escalation_routes(self):
        from argus_agent.api.service_config import escalation_router

        paths = [r.path for r in escalation_router.routes]
        assert "/escalation-policies" in paths
        assert "/escalation-policies/{policy_id}" in paths

    def test_investigations_routes(self):
        from argus_agent.api.investigations import router

        paths = [r.path for r in router.routes]
        assert "/investigations" in paths
        assert "/investigations/{investigation_id}/assign" in paths
        assert "/investigations/{investigation_id}/unassign" in paths
