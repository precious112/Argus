"""Tests for conversation memory and context management."""

from __future__ import annotations

import json

import pytest

from argus_agent.agent.memory import ConversationMemory, _estimate_tokens, _summarize_tool_result
from argus_agent.config import reset_settings
from argus_agent.llm.base import LLMMessage


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


class TestConversationMemory:
    def test_add_user_message(self):
        mem = ConversationMemory()
        mem.add_user_message("Hello")
        assert len(mem.messages) == 1
        assert mem.messages[0].role == "user"
        assert mem.messages[0].content == "Hello"

    def test_add_assistant_message(self):
        mem = ConversationMemory()
        mem.add_assistant_message("Hi there")
        assert len(mem.messages) == 1
        assert mem.messages[0].role == "assistant"

    def test_add_tool_result(self):
        mem = ConversationMemory()
        mem.add_tool_result("tc_1", "log_search", {"matches": []})
        assert len(mem.messages) == 1
        assert mem.messages[0].role == "tool"
        assert mem.messages[0].tool_call_id == "tc_1"
        assert mem.messages[0].name == "log_search"

    def test_context_includes_system_prompt(self):
        mem = ConversationMemory()
        mem.add_user_message("Hello")
        ctx = mem.get_context_messages("You are a helpful agent.")
        assert ctx[0].role == "system"
        assert "helpful agent" in ctx[0].content

    def test_context_includes_messages(self):
        mem = ConversationMemory()
        mem.add_user_message("Hello")
        mem.add_assistant_message("Hi")
        mem.add_user_message("What's the CPU usage?")
        ctx = mem.get_context_messages("System prompt")
        # system + 3 messages
        assert len(ctx) == 4

    def test_truncation_drops_oldest(self):
        mem = ConversationMemory()
        # Add many messages to exceed token budget
        for i in range(100):
            mem.add_user_message(f"Message {i} " + "x" * 200)
            mem.add_assistant_message(f"Response {i} " + "y" * 200)
        ctx = mem.get_context_messages("System prompt")
        # Should have been truncated
        assert len(ctx) < 201  # Less than system + 200 messages

    def test_conversation_id_auto_generated(self):
        mem = ConversationMemory()
        assert len(mem.conversation_id) > 0

    def test_conversation_id_custom(self):
        mem = ConversationMemory(conversation_id="test-123")
        assert mem.conversation_id == "test-123"


class TestTokenEstimation:
    def test_empty_message(self):
        msg = LLMMessage(role="user", content="")
        tokens = _estimate_tokens(msg)
        assert tokens == 4  # Just overhead

    def test_content_estimation(self):
        msg = LLMMessage(role="user", content="Hello world!")
        tokens = _estimate_tokens(msg)
        assert tokens > 4

    def test_tool_calls_included(self):
        msg = LLMMessage(
            role="assistant",
            content="",
            tool_calls=[{"function": {"name": "test"}}],
        )
        tokens = _estimate_tokens(msg)
        assert tokens > 4


class TestToolResultSummarization:
    def test_summarize_error(self):
        result = _summarize_tool_result({"error": "File not found"})
        data = json.loads(result)
        assert data["error"] == "File not found"

    def test_summarize_log_matches(self):
        result = _summarize_tool_result(
            {
                "file": "/var/log/syslog",
                "pattern": "ERROR",
                "total_matches": 5,
                "matches": [
                    {"text": "ERROR: Connection refused", "line_number": 42},
                    {"text": "ERROR: Timeout", "line_number": 43},
                ],
            }
        )
        data = json.loads(result)
        assert data["total_matches"] == 5
        assert data["matches_count"] == 2
        assert "Connection refused" in data["first_match"]

    def test_summarize_long_content_truncated(self):
        long_content = "x" * 1000
        result = _summarize_tool_result({"content": long_content, "path": "/etc/config"})
        data = json.loads(result)
        assert "content_preview" in data
        assert len(data["content_preview"]) < 300
