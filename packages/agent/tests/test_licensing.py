"""Tests for Argus licensing system."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from argus_agent.auth.jwt import create_access_token
from argus_agent.config import reset_settings
from argus_agent.licensing import (
    Edition,
    Feature,
    LicenseManager,
    generate_license_key,
    reset_license_manager,
)
from argus_agent.licensing.editions import EDITION_ORDER
from argus_agent.licensing.manager import LICENSE_ALGORITHM, LICENSE_SIGNING_KEY
from argus_agent.licensing.registry import FEATURE_REGISTRY, has_feature, require_feature
from argus_agent.main import create_app


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    reset_license_manager()
    yield
    reset_settings()
    reset_license_manager()


# ---------------------------------------------------------------------------
# Unit tests: editions & registry
# ---------------------------------------------------------------------------


class TestEditions:
    def test_edition_order(self):
        assert EDITION_ORDER[Edition.COMMUNITY] < EDITION_ORDER[Edition.PRO]
        assert EDITION_ORDER[Edition.PRO] < EDITION_ORDER[Edition.ENTERPRISE]

    def test_all_features_in_registry(self):
        for feature in Feature:
            assert feature in FEATURE_REGISTRY, f"{feature} missing from FEATURE_REGISTRY"

    def test_community_features_are_community(self):
        community_features = [
            Feature.HOST_MONITORING,
            Feature.LOG_ANALYSIS,
            Feature.BASIC_ALERTING,
            Feature.AI_CHAT,
            Feature.SDK_TELEMETRY,
        ]
        for f in community_features:
            assert FEATURE_REGISTRY[f] == Edition.COMMUNITY

    def test_pro_features_are_pro(self):
        pro_features = [
            Feature.TEAM_MANAGEMENT,
            Feature.ADVANCED_INTEGRATIONS,
            Feature.CUSTOM_DASHBOARDS,
        ]
        for f in pro_features:
            assert FEATURE_REGISTRY[f] == Edition.PRO

    def test_enterprise_features_are_enterprise(self):
        enterprise_features = [
            Feature.MULTI_TENANCY,
            Feature.SSO_SAML,
            Feature.ADVANCED_ANALYTICS,
            Feature.SLA_MONITORING,
        ]
        for f in enterprise_features:
            assert FEATURE_REGISTRY[f] == Edition.ENTERPRISE


# ---------------------------------------------------------------------------
# Unit tests: LicenseManager
# ---------------------------------------------------------------------------


class TestLicenseManager:
    def test_no_key_defaults_to_community(self):
        mgr = LicenseManager("")
        assert mgr.edition == Edition.COMMUNITY
        assert mgr.info.valid is True
        assert mgr.info.error == ""

    def test_invalid_key_falls_back_to_community(self):
        mgr = LicenseManager("not-a-valid-jwt")
        assert mgr.edition == Edition.COMMUNITY
        assert mgr.info.valid is False

    def test_expired_key_falls_back_to_community(self):
        payload = {
            "edition": "pro",
            "holder": "test-org",
            "exp": datetime.now(UTC) - timedelta(days=1),
            "iat": datetime.now(UTC) - timedelta(days=30),
        }
        expired_key = jwt.encode(payload, LICENSE_SIGNING_KEY, algorithm=LICENSE_ALGORITHM)
        mgr = LicenseManager(expired_key)
        assert mgr.edition == Edition.COMMUNITY
        assert mgr.info.error == "expired"

    def test_pro_key_roundtrip(self):
        key = generate_license_key(Edition.PRO, "test-org", expires_days=30)
        mgr = LicenseManager(key)
        assert mgr.edition == Edition.PRO
        assert mgr.info.holder == "test-org"
        assert mgr.info.valid is True

    def test_enterprise_key_roundtrip(self):
        key = generate_license_key(Edition.ENTERPRISE, "big-corp", expires_days=365, max_nodes=100)
        mgr = LicenseManager(key)
        assert mgr.edition == Edition.ENTERPRISE
        assert mgr.info.holder == "big-corp"
        assert mgr.info.max_nodes == 100

    def test_community_features_subset(self):
        mgr = LicenseManager("")
        features = mgr.get_enabled_features()
        assert Feature.HOST_MONITORING in features
        assert Feature.AI_CHAT in features
        assert Feature.TEAM_MANAGEMENT not in features
        assert Feature.MULTI_TENANCY not in features

    def test_pro_features_include_community(self):
        key = generate_license_key(Edition.PRO, "test-org")
        mgr = LicenseManager(key)
        features = mgr.get_enabled_features()
        # Should have community features
        assert Feature.HOST_MONITORING in features
        # Should have pro features
        assert Feature.TEAM_MANAGEMENT in features
        assert Feature.CUSTOM_DASHBOARDS in features
        # Should NOT have enterprise features
        assert Feature.MULTI_TENANCY not in features

    def test_enterprise_features_include_all(self):
        key = generate_license_key(Edition.ENTERPRISE, "test-org")
        mgr = LicenseManager(key)
        features = mgr.get_enabled_features()
        # Should have all features
        for feature in Feature:
            assert feature in features

    def test_to_dict_structure(self):
        key = generate_license_key(Edition.PRO, "test-org", expires_days=30)
        mgr = LicenseManager(key)
        d = mgr.to_dict()
        assert d["edition"] == "pro"
        assert d["holder"] == "test-org"
        assert d["valid"] is True
        assert isinstance(d["features"], list)
        assert "team_management" in d["features"]

    def test_unknown_edition_falls_back(self):
        payload = {
            "edition": "platinum",
            "holder": "test-org",
            "exp": datetime.now(UTC) + timedelta(days=30),
            "iat": datetime.now(UTC),
        }
        key = jwt.encode(payload, LICENSE_SIGNING_KEY, algorithm=LICENSE_ALGORITHM)
        mgr = LicenseManager(key)
        assert mgr.edition == Edition.COMMUNITY
        assert mgr.info.error == "unknown_edition"


# ---------------------------------------------------------------------------
# Unit tests: gating helpers
# ---------------------------------------------------------------------------


class TestGating:
    def test_has_feature_community(self):
        from argus_agent.licensing import init_license_manager

        init_license_manager("")
        assert has_feature(Feature.HOST_MONITORING) is True
        assert has_feature(Feature.TEAM_MANAGEMENT) is False

    def test_has_feature_pro(self):
        from argus_agent.licensing import init_license_manager

        key = generate_license_key(Edition.PRO, "test-org")
        init_license_manager(key)
        assert has_feature(Feature.TEAM_MANAGEMENT) is True
        assert has_feature(Feature.MULTI_TENANCY) is False

    def test_require_feature_passes(self):
        from argus_agent.licensing import init_license_manager

        key = generate_license_key(Edition.PRO, "test-org")
        init_license_manager(key)
        check = require_feature(Feature.TEAM_MANAGEMENT)
        check()  # Should not raise

    def test_require_feature_raises_403(self):
        from fastapi import HTTPException

        from argus_agent.licensing import init_license_manager

        init_license_manager("")
        check = require_feature(Feature.TEAM_MANAGEMENT)
        with pytest.raises(HTTPException) as exc_info:
            check()
        assert exc_info.value.status_code == 403
        detail = exc_info.value.detail
        assert detail["error"] == "feature_not_licensed"
        assert detail["feature"] == "team_management"
        assert detail["required_edition"] == "pro"
        assert detail["current_edition"] == "community"


# ---------------------------------------------------------------------------
# Unit tests: keygen
# ---------------------------------------------------------------------------


class TestKeygen:
    def test_generate_string_edition(self):
        key = generate_license_key("pro", "test-org")
        mgr = LicenseManager(key)
        assert mgr.edition == Edition.PRO

    def test_custom_max_nodes(self):
        key = generate_license_key(Edition.PRO, "test-org", max_nodes=50)
        mgr = LicenseManager(key)
        assert mgr.info.max_nodes == 50

    def test_custom_expiry(self):
        key = generate_license_key(Edition.PRO, "test-org", expires_days=7)
        mgr = LicenseManager(key)
        assert mgr.info.expires_at is not None
        delta = mgr.info.expires_at - datetime.now(UTC)
        # delta.days can be 6 due to sub-second timing
        assert delta.days in (6, 7)


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    token = create_access_token("test-user-id", "test")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"argus_token": token},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_license_endpoint_community(client):
    resp = await client.get("/api/v1/license")
    assert resp.status_code == 200
    data = resp.json()
    assert data["edition"] == "community"
    assert "host_monitoring" in data["features"]
    assert "team_management" not in data["features"]


@pytest.mark.asyncio
async def test_license_endpoint_no_auth(app):
    """License endpoint should be accessible without authentication."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/license")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_includes_edition(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["edition"] == "community"


@pytest.mark.asyncio
async def test_license_endpoint_with_pro_key(app):
    from argus_agent.licensing import init_license_manager

    key = generate_license_key(Edition.PRO, "test-org")
    init_license_manager(key)
    token = create_access_token("test-user-id", "test")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"argus_token": token},
    ) as c:
        resp = await c.get("/api/v1/license")
    assert resp.status_code == 200
    data = resp.json()
    assert data["edition"] == "pro"
    assert "team_management" in data["features"]
    assert "multi_tenancy" not in data["features"]
