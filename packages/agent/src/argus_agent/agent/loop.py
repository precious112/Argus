"""ReAct reasoning loop for the Argus agent."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from argus_agent.agent.memory import ConversationMemory
from argus_agent.agent.prompt import build_system_prompt
from argus_agent.llm.base import LLMMessage, LLMProvider
from argus_agent.tools.base import Tool, get_tool, get_tool_definitions

logger = logging.getLogger("argus.agent.loop")

MAX_TOOL_ROUNDS = 20


async def _try_remote_execute(
    tool_name: str,
    tool_args: dict[str, Any],
) -> dict[str, Any] | None:
    """Attempt to execute a tool via remote webhook in SaaS mode.

    Returns None if the tool should be executed locally.
    """
    try:
        from argus_agent.tenancy.context import get_tenant_id
        from argus_agent.webhooks.tool_router import execute_tool as remote_execute

        tenant_id = get_tenant_id()
        return await remote_execute(tool_name, tool_args, tenant_id)
    except Exception:
        logger.debug("Remote tool routing skipped for %s", tool_name, exc_info=True)
        return None


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
        source: str = "agent_loop",
    ) -> None:
        self.provider = provider
        self.memory = memory
        self._on_event = on_event
        self._budget = budget  # Optional TokenBudget for background tasks
        self._client_type = client_type
        self._source = source

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

        for round_num in range(MAX_TOOL_ROUNDS):
            result.rounds = round_num + 1

            # Build context
            messages = self.memory.get_context_messages(system_prompt)

            # On the final round, force a summary (no tools available)
            is_final_round = round_num == MAX_TOOL_ROUNDS - 1
            if is_final_round:
                tool_defs_for_round = None
                messages.append(LLMMessage(
                    role="user",
                    content=(
                        "[SYSTEM] You have used all available tool call rounds. "
                        "Do NOT attempt any more tool calls or announce future actions. "
                        "Summarize your findings so far clearly and concisely."
                    ),
                ))
            else:
                tool_defs_for_round = tool_defs

            # Call LLM with streaming
            await self._emit("thinking_start", {})

            full_content = ""
            all_tool_calls: list[dict[str, Any]] = []
            response_metadata: dict[str, Any] = {}

            # Track per-round deltas to avoid double-counting
            prompt_before = result.prompt_tokens
            completion_before = result.completion_tokens

            async for delta in self.provider.stream(messages, tools=tool_defs_for_round or None):
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

            # Compute per-round deltas
            round_prompt = result.prompt_tokens - prompt_before
            round_completion = result.completion_tokens - completion_before

            # Record token usage in budget (per-round, not cumulative)
            if round_prompt or round_completion:
                if self._budget:
                    self._budget.record_usage(
                        round_prompt, round_completion, source=self._source
                    )
                # Persist to DB
                try:
                    from argus_agent.storage.token_usage import TokenUsageService

                    svc = TokenUsageService()
                    await svc.record(
                        prompt_tokens=round_prompt,
                        completion_tokens=round_completion,
                        provider=self.provider.name,
                        model=self.provider.model,
                        source=self._source,
                        conversation_id=getattr(self.memory, "conversation_id", ""),
                    )
                except Exception:
                    logger.debug("Failed to persist token usage", exc_info=True)

            # If the LLM wants to call tools
            if all_tool_calls:
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

                    # Execute the tool — try remote webhook first (SaaS mode)
                    tool = get_tool(tool_name)
                    if tool is None:
                        tool_result = {"error": f"Unknown tool: {tool_name}"}
                    else:
                        try:
                            args = _coerce_args(tool, args)

                            # Route to remote SDK webhook if configured
                            remote_result = await _try_remote_execute(tool_name, args)
                            if remote_result is not None:
                                tool_result = remote_result
                            else:
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

            # No tool calls — this is the final answer.
            result.content = full_content
            if full_content:
                self.memory.add_assistant_message(content=full_content)

            return result

        # Exhausted max rounds — always append notice so the user knows
        exhaustion_msg = (
            "\n\n---\n*I've reached the maximum number of tool call rounds for this turn.*"
        )
        result.content = (result.content or "") + exhaustion_msg
        await self._emit("assistant_message_delta", {"content": exhaustion_msg})
        self.memory.add_assistant_message(content=result.content)
        return result
