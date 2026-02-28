"""Tests for telemetry ingest endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from argus_agent.api.ingest import IngestBatch, TelemetryEvent, router


@pytest.fixture
def client():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


class TestIngestEndpoint:
    def test_ingest_batch(self, client):
        mock_repo = MagicMock()
        with patch("argus_agent.storage.repositories.get_metrics_repository", return_value=mock_repo):
            resp = client.post("/api/v1/ingest", json={
                "events": [
                    {"type": "log", "service": "test-app", "data": {"message": "hello"}},
                    {"type": "event", "service": "test-app", "data": {"name": "click"}},
                ],
                "sdk": "argus-python/0.1.0",
                "service": "test-app",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["accepted"] == 2

    def test_ingest_empty_batch(self, client):
        mock_repo = MagicMock()
        with patch("argus_agent.storage.repositories.get_metrics_repository", return_value=mock_repo):
            resp = client.post("/api/v1/ingest", json={
                "events": [],
                "sdk": "argus-python/0.1.0",
            })
            assert resp.status_code == 200
            assert resp.json()["accepted"] == 0

    def test_ingest_too_large_batch(self, client):
        events = [{"type": "log", "data": {}} for _ in range(1001)]
        resp = client.post("/api/v1/ingest", json={
            "events": events,
            "sdk": "test",
        })
        assert resp.status_code == 400

    def test_ingest_with_exception_event(self, client):
        mock_repo = MagicMock()
        with patch("argus_agent.storage.repositories.get_metrics_repository", return_value=mock_repo):
            with patch("argus_agent.events.bus.get_event_bus") as mock_bus:
                mock_bus.return_value.publish = MagicMock()
                resp = client.post("/api/v1/ingest", json={
                    "events": [
                        {
                            "type": "exception",
                            "service": "test-app",
                            "data": {"message": "NullPointerException", "type": "Error"},
                        },
                    ],
                    "sdk": "argus-python/0.1.0",
                    "service": "test-app",
                })
                assert resp.status_code == 200

    def test_ingest_duckdb_not_initialized(self, client):
        with patch("argus_agent.storage.repositories.get_metrics_repository", side_effect=RuntimeError("not init")):
            resp = client.post("/api/v1/ingest", json={
                "events": [{"type": "log", "data": {}}],
                "sdk": "test",
            })
            assert resp.status_code == 200
            assert resp.json()["accepted"] == 0

    def test_telemetry_event_model(self):
        ev = TelemetryEvent(type="log", service="svc", data={"key": "val"})
        assert ev.type == "log"
        assert ev.service == "svc"

    def test_ingest_batch_model(self):
        batch = IngestBatch(
            events=[TelemetryEvent(type="log")],
            sdk="test/0.1.0",
            service="svc",
        )
        assert len(batch.events) == 1
        assert batch.sdk == "test/0.1.0"

    def test_ingest_with_api_key_header(self, client):
        mock_repo = MagicMock()
        with patch("argus_agent.storage.repositories.get_metrics_repository", return_value=mock_repo):
            resp = client.post(
                "/api/v1/ingest",
                json={"events": [{"type": "log", "data": {}}], "sdk": "test"},
                headers={"x-argus-key": "my-api-key"},
            )
            assert resp.status_code == 200
