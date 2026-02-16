"""ReAct reasoning loop for the Argus agent."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from argus_agent.agent.memory import ConversationMemory
from argus_agent.agent.prompt import build_system_prompt
from argus_agent.llm.base import LLMProvider
from argus_agent.tools.base import Tool, get_tool, get_tool_definitions

logger = logging.getLogger("argus.agent.loop")

MAX_TOOL_ROUNDS = 10


def _coerce_args(tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
    """Coerce tool arguments to match declared schema types.

    Some LLM providers (e.g. Gemini) may send integers as floats.
    """
    props = tool.parameters_schema.get("properties", {})
    for key, value in args.items():
        if key not in props:
            continue
        declared = props[key].get("type")
        if declared == "integer" and isinstance(value, float):
            args[key] = int(value)
    return args


# Type alias for event callbacks
EventCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class AgentResult:
    """Result of a single agent turn."""

    content: str = ""
    tool_calls_made: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    rounds: int = 0


class AgentLoop:
    """ReAct reasoning loop that powers all three agent modes.

    The loop:
    1. Assembles context (system prompt + conversation history)
    2. Calls the LLM (with streaming)
    3. If LLM returns tool calls, executes them and loops back
    4. If LLM returns text, streams it to the user and finishes
    5. Capped at MAX_TOOL_ROUNDS to prevent runaway cost
    """

    def __init__(
        self,
        provider: LLMProvider,
        memory: ConversationMemory,
        on_event: EventCallback | None = None,
        budget: Any | None = None,
        client_type: str = "web",
    ) -> None:
        self.provider = provider
        self.memory = memory
        self._on_event = on_event
        self._budget = budget  # Optional TokenBudget for background tasks
        self._client_type = client_type

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to the callback (e.g., WebSocket handler)."""
        if self._on_event:
            await self._on_event(event_type, data)

    async def run(self, user_message: str) -> AgentResult:
        """Execute the full ReAct loop for a user message."""
        # Add user message to memory
        self.memory.add_user_message(user_message)

        result = AgentResult()
        from argus_agent.config import get_settings

        system_prompt = build_system_prompt(
            client_type=self._client_type,
            mode=get_settings().mode,
        )
        tool_defs = get_tool_definitions()

        _max_text_only_continuations = 2
        _consecutive_text_only = 0

        for round_num in range(MAX_TOOL_ROUNDS):
            result.rounds = round_num + 1

            # Build context
            messages = self.memory.get_context_messages(system_prompt)

            # Call LLM with streaming
            await self._emit("thinking_start", {})

            full_content = ""
            all_tool_calls: list[dict[str, Any]] = []
            response_metadata: dict[str, Any] = {}

            async for delta in self.provider.stream(messages, tools=tool_defs or None):
                # Stream text content to the user
                if delta.content:
                    full_content += delta.content
                    await self._emit("assistant_message_delta", {"content": delta.content})

                # Collect accumulated tool calls from final chunk
                if delta.tool_calls:
                    all_tool_calls = delta.tool_calls

                # Capture provider-specific metadata (e.g. Gemini thought_signatures)
                if delta.metadata:
                    response_metadata.update(delta.metadata)

                result.prompt_tokens += delta.prompt_tokens
                result.completion_tokens += delta.completion_tokens

            await self._emit("thinking_end", {})

            # Record token usage in budget if set
            if self._budget and (result.prompt_tokens or result.completion_tokens):
                self._budget.record_usage(
                    result.prompt_tokens, result.completion_tokens, source="agent_loop"
                )

            # If the LLM wants to call tools
            if all_tool_calls:
                _consecutive_text_only = 0  # Reset on tool calls

                # Add assistant message with tool calls to memory
                self.memory.add_assistant_message(
                    content=full_content,
                    tool_calls=all_tool_calls,
                    metadata=response_metadata,
                )
                result.tool_calls_made += len(all_tool_calls)

                # Execute each tool call
                for tc in all_tool_calls:
                    tool_name = tc["function"]["name"]
                    tool_call_id = tc["id"]

                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        args = {}

                    await self._emit(
                        "tool_call",
                        {"id": tool_call_id, "name": tool_name, "arguments": args},
                    )

                    # Execute the tool
                    tool = get_tool(tool_name)
                    if tool is None:
                        tool_result = {"error": f"Unknown tool: {tool_name}"}
                    else:
                        try:
                            args = _coerce_args(tool, args)
                            tool_result = await tool.execute(**args)
                        except Exception as e:
                            logger.exception("Tool execution error: %s", tool_name)
                            tool_result = {"error": f"Tool execution failed: {e}"}

                    await self._emit(
                        "tool_result",
                        {
                            "id": tool_call_id,
                            "name": tool_name,
                            "result": tool_result,
                            "display_type": tool_result.get("display_type", "json_tree"),
                        },
                    )

                    # Add tool result to memory
                    self.memory.add_tool_result(tool_call_id, tool_name, tool_result)

                # Loop back for next LLM call with tool results
                continue

            # No tool calls in this response
            if full_content:
                self.memory.add_assistant_message(content=full_content)

            # If we previously made tool calls this turn, allow a few
            # consecutive text-only rounds — the LLM may need to comment
            # before issuing the next tool call (e.g. query → explain → chart).
            if result.tool_calls_made > 0 and _consecutive_text_only < _max_text_only_continuations:
                _consecutive_text_only += 1
                continue

            result.content = full_content
            return result

        # Exhausted max rounds
        exhaustion_msg = (
            "I've reached the maximum number of tool calls for this turn. "
            "Here's what I found so far based on the tools I've used."
        )
        if not result.content:
            result.content = exhaustion_msg
            await self._emit("assistant_message_delta", {"content": exhaustion_msg})
        self.memory.add_assistant_message(content=result.content)
        return result
