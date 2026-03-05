"""Tests that the ingest endpoint enforces event billing limits in SaaS mode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from argus_agent.api.ingest import router

_GUARD = "argus_agent.billing.usage_guard"
_INGEST = "argus_agent.api.ingest"
_REPO = "argus_agent.storage.repositories.get_metrics_repository"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _ingest_payload():
    return {
        "events": [{"type": "log", "service": "svc", "data": {"msg": "hi"}}],
        "sdk": "test/0.1.0",
        "service": "svc",
    }


class TestIngestBillingEnforcement:
    def test_ingest_returns_429_when_over_limit(self, client):
        """SaaS mode: ingest should reject with 429 when event limit exceeded."""
        from fastapi import HTTPException

        async def _reject_limit(tenant_id: str, *, batch_size: int = 1) -> None:
            raise HTTPException(429, "Monthly event limit reached")

        mock_repo = MagicMock()
        with (
            patch(f"{_INGEST}._validate_ingest_key", new_callable=AsyncMock),
            patch(
                f"{_GUARD}.check_event_ingest_limit",
                side_effect=_reject_limit,
            ),
            patch(_REPO, return_value=mock_repo),
        ):
            resp = client.post("/api/v1/ingest", json=_ingest_payload())
            assert resp.status_code == 429
            assert "limit" in resp.json()["detail"].lower()
            # Events should NOT be stored
            mock_repo.insert_sdk_event.assert_not_called()

    def test_ingest_succeeds_when_under_limit(self, client):
        """SaaS mode: ingest should succeed when under event limit."""
        mock_repo = MagicMock()
        with (
            patch(f"{_INGEST}._validate_ingest_key", new_callable=AsyncMock),
            patch(
                f"{_GUARD}.check_event_ingest_limit",
                new_callable=AsyncMock,
            ),
            patch(_REPO, return_value=mock_repo),
        ):
            resp = client.post("/api/v1/ingest", json=_ingest_payload())
            assert resp.status_code == 200
            assert resp.json()["accepted"] == 1

    def test_self_hosted_no_billing_check(self, client):
        """Self-hosted mode: billing guard is a no-op, ingest works normally."""
        mock_repo = MagicMock()
        with (
            patch(f"{_INGEST}._validate_ingest_key", new_callable=AsyncMock),
            patch(f"{_GUARD}._is_saas", return_value=False),
            patch(_REPO, return_value=mock_repo),
        ):
            resp = client.post("/api/v1/ingest", json=_ingest_payload())
            assert resp.status_code == 200
            assert resp.json()["accepted"] == 1

    def test_batch_overflow_rejected(self, client):
        """A batch that pushes count over the limit should be rejected."""
        from fastapi import HTTPException

        async def _reject_limit(tenant_id: str, *, batch_size: int = 1) -> None:
            raise HTTPException(429, "Monthly event limit reached")

        mock_repo = MagicMock()
        payload = {
            "events": [
                {"type": "log", "service": "svc", "data": {"msg": f"e{i}"}}
                for i in range(50)
            ],
            "sdk": "test/0.1.0",
            "service": "svc",
        }
        with (
            patch(f"{_INGEST}._validate_ingest_key", new_callable=AsyncMock),
            patch(
                f"{_GUARD}.check_event_ingest_limit",
                side_effect=_reject_limit,
            ),
            patch(_REPO, return_value=mock_repo),
        ):
            resp = client.post("/api/v1/ingest", json=payload)
            assert resp.status_code == 429
            mock_repo.insert_sdk_event.assert_not_called()
