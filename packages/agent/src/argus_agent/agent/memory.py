"""Context and conversation management for the agent."""

from __future__ import annotations

import json
import logging
import uuid

from argus_agent.llm.base import LLMMessage
from argus_agent.storage.database import get_session
from argus_agent.storage.models import Conversation, Message

logger = logging.getLogger("argus.agent.memory")

# Context budget in estimated tokens
MAX_HISTORY_TOKENS = 4000
TOOL_RESULT_SUMMARY_AFTER = 2  # Summarize tool results older than N turns


class ConversationMemory:
    """Manages conversation history and context assembly for the agent."""

    def __init__(self, conversation_id: str | None = None, source: str = "user") -> None:
        self.conversation_id = conversation_id or str(uuid.uuid4())
        self.source = source
        self.messages: list[LLMMessage] = []
        self._persisted = False

    async def persist_conversation(self, title: str = "") -> None:
        """Create conversation record in the database."""
        if self._persisted:
            return
        async with get_session() as session:
            conv = Conversation(
                id=self.conversation_id,
                title=title or "New conversation",
                source=self.source,
            )
            session.add(conv)
            await session.commit()
        self._persisted = True

    async def persist_message(
        self,
        role: str,
        content: str = "",
        tool_calls: list[dict] | None = None,
        tool_result: dict | None = None,
        token_count: int = 0,
    ) -> str:
        """Persist a single message to the database."""
        msg_id = str(uuid.uuid4())
        async with get_session() as session:
            msg = Message(
                id=msg_id,
                conversation_id=self.conversation_id,
                role=role,
                content=content,
                tool_calls=tool_calls,
                tool_result=tool_result,
                token_count=token_count,
            )
            session.add(msg)
            await session.commit()
        return msg_id

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation."""
        self.messages.append(LLMMessage(role="user", content=content))

    def add_assistant_message(
        self, content: str = "", tool_calls: list[dict] | None = None
    ) -> None:
        """Add an assistant message (possibly with tool calls)."""
        self.messages.append(
            LLMMessage(role="assistant", content=content, tool_calls=tool_calls or [])
        )

    def add_tool_result(self, tool_call_id: str, name: str, result: dict) -> None:
        """Add a tool result message."""
        self.messages.append(
            LLMMessage(
                role="tool",
                content=json.dumps(result),
                tool_call_id=tool_call_id,
                name=name,
            )
        )

    def get_context_messages(self, system_prompt: str) -> list[LLMMessage]:
        """Build the full message list for an LLM call.

        Applies sliding window and smart truncation to stay within token budget.
        """
        context = [LLMMessage(role="system", content=system_prompt)]

        # Apply smart truncation to conversation history
        history = self._truncate_history(self.messages)
        context.extend(history)

        return context

    def _truncate_history(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Smart truncation of conversation history.

        - Keep all recent messages intact
        - Summarize older tool results to save tokens
        - Drop oldest messages if still over budget
        """
        if not messages:
            return []

        result = list(messages)

        # Summarize old tool results (keep recent ones intact)
        if len(result) > TOOL_RESULT_SUMMARY_AFTER * 3:
            cutoff = len(result) - TOOL_RESULT_SUMMARY_AFTER * 3
            for i in range(cutoff):
                if result[i].role == "tool" and len(result[i].content) > 200:
                    try:
                        data = json.loads(result[i].content)
                        summary = _summarize_tool_result(data)
                        result[i] = LLMMessage(
                            role="tool",
                            content=summary,
                            tool_call_id=result[i].tool_call_id,
                            name=result[i].name,
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass

        # Estimate token usage and drop oldest if over budget
        total_tokens = sum(_estimate_tokens(m) for m in result)
        while total_tokens > MAX_HISTORY_TOKENS and len(result) > 2:
            dropped = result.pop(0)
            total_tokens -= _estimate_tokens(dropped)

        return result


def _estimate_tokens(msg: LLMMessage) -> int:
    """Rough token estimate for a message."""
    text = msg.content
    if msg.tool_calls:
        text += json.dumps(msg.tool_calls)
    return len(text) // 4 + 4  # ~4 chars per token + message overhead


def _summarize_tool_result(data: dict) -> str:
    """Create a compact summary of a tool result."""
    if "error" in data:
        return json.dumps({"error": data["error"]})

    summary: dict = {}
    # Keep key metadata, drop large content
    for key in ("file", "path", "pattern", "total_matches", "total_lines", "returned"):
        if key in data:
            summary[key] = data[key]

    if "matches" in data:
        count = len(data["matches"])
        summary["matches_count"] = count
        if count > 0:
            summary["first_match"] = data["matches"][0].get("text", "")[:100]

    if "lines" in data and isinstance(data["lines"], list):
        summary["lines_count"] = len(data["lines"])

    if "content" in data:
        content = data["content"]
        if len(content) > 200:
            summary["content_preview"] = content[:200] + "..."
        else:
            summary["content"] = content

    return json.dumps(summary) if summary else json.dumps({"status": "ok"})
