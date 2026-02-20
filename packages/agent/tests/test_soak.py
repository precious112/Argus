"""Tests for soak test runner utilities."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from unittest.mock import patch

import pytest

from argus_agent.scheduler.soak import (
    SoakAppConfig,
    SoakTestRunner,
    _create_executable_artifact,
    _emit_error_burst,
    _pick_endpoint,
    parse_soak_apps,
)


class TestParseSoakApps:
    """Tests for parse_soak_apps()."""

    def test_empty_env(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARGUS_SOAK_APPS", None)
            assert parse_soak_apps() == []

    def test_valid_json(self) -> None:
        apps = [
            {
                "path": "examples/python-fastapi",
                "cmd": "python app.py",
                "port": 8081,
                "env": {"PORT": "8081"},
            },
            {"path": "examples/node-express", "cmd": "node app.js", "port": 8082},
        ]
        with patch.dict(os.environ, {"ARGUS_SOAK_APPS": json.dumps(apps)}):
            result = parse_soak_apps()
            assert len(result) == 2
            assert isinstance(result[0], SoakAppConfig)
            assert result[0].port == 8081
            assert result[0].env == {"PORT": "8081"}
            assert result[1].env == {}

    def test_invalid_json(self) -> None:
        with patch.dict(os.environ, {"ARGUS_SOAK_APPS": "not-json"}):
            assert parse_soak_apps() == []

    def test_missing_required_fields(self) -> None:
        with patch.dict(os.environ, {"ARGUS_SOAK_APPS": '[{"path":"a"}]'}):
            assert parse_soak_apps() == []


class TestPickEndpoint:
    """Tests for weighted endpoint selection."""

    def test_returns_valid_endpoint(self) -> None:
        valid = {"/", "/error", "/slow", "/chain", "/users", "/checkout", "/multi-error"}
        for _ in range(100):
            ep = _pick_endpoint()
            assert ep in valid

    def test_distribution_rough(self) -> None:
        """Normal endpoints should appear most often."""
        counts: dict[str, int] = {}
        n = 10_000
        for _ in range(n):
            ep = _pick_endpoint()
            counts[ep] = counts.get(ep, 0) + 1

        # "/" has weight 40/100 = 40%, so should be > 30% over many trials
        assert counts.get("/", 0) > n * 0.3
        # "/error" has weight 20/100 = 20%
        assert counts.get("/error", 0) > n * 0.1


class TestCreateExecutableArtifact:
    """Tests for _create_executable_artifact()."""

    def test_creates_executable_file(self) -> None:
        path = _create_executable_artifact()
        try:
            assert os.path.exists(path)
            assert os.stat(path).st_mode & stat.S_IEXEC
            assert "soak_test_" in os.path.basename(path)
        finally:
            os.unlink(path)


class TestEmitErrorBurst:
    """Tests for _emit_error_burst()."""

    def test_emits_correct_count(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.ERROR, logger="argus.soak.error_burst"):
            _emit_error_burst(count=5)
        error_msgs = [
            r for r in caplog.records
            if r.levelno == logging.ERROR
            and "error burst" in r.message.lower()
        ]
        assert len(error_msgs) == 5


class TestSoakTestRunner:
    """Tests for SoakTestRunner initialization and config."""

    def test_default_intervals(self) -> None:
        runner = SoakTestRunner()
        assert runner._cpu_interval == 20 * 60
        assert runner._mem_interval == 30 * 60
        assert runner._traffic_interval == 30

    def test_no_apps_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARGUS_SOAK_APPS", None)
            runner = SoakTestRunner()
            assert runner._app_configs == []

    def test_cleanup_artifacts(self) -> None:
        runner = SoakTestRunner()
        # Create temp files and add to artifacts
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        runner._artifacts.append(tmp.name)
        assert os.path.exists(tmp.name)

        runner._cleanup_artifacts()
        assert not os.path.exists(tmp.name)
        assert runner._artifacts == []
