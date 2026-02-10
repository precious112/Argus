"""Tests for agent tools."""

from __future__ import annotations

import pytest

from argus_agent.config import reset_settings
from argus_agent.tools.log_search import FileReadTool, LogSearchTool, LogTailTool


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def sample_log(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text(
        "2024-01-01 INFO Starting application\n"
        "2024-01-01 INFO Connected to database\n"
        "2024-01-01 WARN High memory usage detected\n"
        "2024-01-01 ERROR Failed to connect to redis\n"
        "2024-01-01 ERROR Connection refused: redis:6379\n"
        "2024-01-01 INFO Retrying connection...\n"
        "2024-01-01 INFO Connected to redis\n"
        "2024-01-01 INFO Ready to serve requests\n"
    )
    return str(log_file)


@pytest.fixture
def sample_config(tmp_path):
    config_file = tmp_path / "app.conf"
    config_file.write_text(
        "[server]\nhost = 0.0.0.0\nport = 8080\n\n[database]\nurl = postgres://localhost/mydb\n"
    )
    return str(config_file)


class TestLogSearch:
    @pytest.mark.asyncio
    async def test_search_pattern(self, sample_log):
        tool = LogSearchTool()
        result = await tool.execute(pattern="ERROR", file=sample_log)
        assert result["total_matches"] == 2
        assert "redis" in result["matches"][0]["text"]

    @pytest.mark.asyncio
    async def test_search_regex(self, sample_log):
        tool = LogSearchTool()
        result = await tool.execute(pattern=r"connect\w+", file=sample_log, case_insensitive=True)
        assert result["total_matches"] >= 2

    @pytest.mark.asyncio
    async def test_search_with_context(self, sample_log):
        tool = LogSearchTool()
        result = await tool.execute(pattern="ERROR", file=sample_log, context_lines=1)
        assert len(result["matches"][0]["context"]) >= 2

    @pytest.mark.asyncio
    async def test_search_file_not_found(self):
        tool = LogSearchTool()
        result = await tool.execute(pattern="test", file="/nonexistent/file.log")
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_search_invalid_regex(self, sample_log):
        tool = LogSearchTool()
        result = await tool.execute(pattern="[invalid", file=sample_log)
        assert "error" in result
        assert "regex" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_search_max_results(self, sample_log):
        tool = LogSearchTool()
        result = await tool.execute(pattern=".", file=sample_log, max_results=2)
        assert result["total_matches"] == 2
        assert result["truncated"] is True


class TestLogTail:
    @pytest.mark.asyncio
    async def test_tail_default(self, sample_log):
        tool = LogTailTool()
        result = await tool.execute(file=sample_log)
        assert result["total_lines"] == 8
        assert result["returned"] == 8

    @pytest.mark.asyncio
    async def test_tail_limited(self, sample_log):
        tool = LogTailTool()
        result = await tool.execute(file=sample_log, lines=3)
        assert result["returned"] == 3
        assert "Ready" in result["lines"][-1]["text"]

    @pytest.mark.asyncio
    async def test_tail_file_not_found(self):
        tool = LogTailTool()
        result = await tool.execute(file="/nonexistent/file.log")
        assert "error" in result


class TestFileRead:
    @pytest.mark.asyncio
    async def test_read_file(self, sample_config):
        tool = FileReadTool()
        result = await tool.execute(path=sample_config)
        assert "host = 0.0.0.0" in result["content"]
        assert result["total_lines"] == 6

    @pytest.mark.asyncio
    async def test_read_with_range(self, sample_config):
        tool = FileReadTool()
        result = await tool.execute(path=sample_config, start_line=1, end_line=3)
        assert "[server]" in result["content"]
        assert result["start_line"] == 1

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        tool = FileReadTool()
        result = await tool.execute(path="/nonexistent/file.conf")
        assert "error" in result


class TestToolDefinitions:
    def test_log_search_definition(self):
        tool = LogSearchTool()
        defn = tool.to_definition()
        assert defn.name == "log_search"
        assert "pattern" in defn.parameters["properties"]
        assert "file" in defn.parameters["properties"]

    def test_log_tail_definition(self):
        tool = LogTailTool()
        defn = tool.to_definition()
        assert defn.name == "log_tail"

    def test_file_read_definition(self):
        tool = FileReadTool()
        defn = tool.to_definition()
        assert defn.name == "file_read"
