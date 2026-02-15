"""WebSocket chat handler for Argus agent server."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from argus_agent.agent.loop import AgentLoop
from argus_agent.agent.memory import ConversationMemory
from argus_agent.api.protocol import (
    ClientMessage,
    ClientMessageType,
    ServerMessage,
    ServerMessageType,
)

logger = logging.getLogger("argus.ws")

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manage active WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send(self, websocket: WebSocket, message: ServerMessage) -> None:
        await websocket.send_json(message.model_dump(mode="json"))

    async def broadcast(self, message: ServerMessage) -> None:
        for connection in self.active_connections:
            try:
                await connection.send_json(message.model_dump(mode="json"))
            except Exception:
                logger.warning("Failed to broadcast to a connection")


manager = ConnectionManager()


def _get_provider():  # type: ignore[no-untyped-def]
    """Get the LLM provider, returning None if not configured."""
    try:
        from argus_agent.llm.registry import get_provider

        return get_provider()
    except Exception as e:
        logger.warning("LLM provider not available: %s", e)
        return None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, client: str = "web") -> None:
    """Main WebSocket endpoint for chat communication."""
    await manager.connect(websocket)
    client_type = client if client in ("cli", "web") else "web"

    # Send connected message with initial system status
    from argus_agent.collectors.system_metrics import get_system_snapshot

    await manager.send(
        websocket,
        ServerMessage(
            type=ServerMessageType.CONNECTED,
            data={"message": "Connected to Argus agent"},
        ),
    )

    # Send initial system status
    snapshot = get_system_snapshot()
    if snapshot:
        await manager.send(
            websocket,
            ServerMessage(
                type=ServerMessageType.SYSTEM_STATUS,
                data=snapshot,
            ),
        )

    # Per-connection conversation memory
    memory = ConversationMemory()
    agent_task: asyncio.Task | None = None  # type: ignore[type-arg]

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = ClientMessage.model_validate_json(raw)
            except Exception:
                await manager.send(
                    websocket,
                    ServerMessage(
                        type=ServerMessageType.ERROR,
                        data={"message": "Invalid message format"},
                    ),
                )
                continue

            if msg.type == ClientMessageType.PING:
                await manager.send(
                    websocket,
                    ServerMessage(type=ServerMessageType.PONG),
                )

            elif msg.type == ClientMessageType.USER_MESSAGE:
                content = msg.data.get("content", "")
                if not content:
                    continue

                if agent_task and not agent_task.done():
                    await manager.send(
                        websocket,
                        ServerMessage(
                            type=ServerMessageType.ERROR,
                            data={"message": "Agent is busy, please wait."},
                        ),
                    )
                    continue

                # Run in background so the WebSocket loop stays free to
                # receive action_response messages (approval/rejection).
                agent_task = asyncio.create_task(
                    _handle_user_message(websocket, memory, content, client_type)
                )

            elif msg.type == ClientMessageType.ACTION_RESPONSE:
                logger.info("Action response received: %s", msg.data)
                from argus_agent.main import _get_action_engine

                engine = _get_action_engine()
                if engine:
                    engine.handle_response(
                        action_id=msg.data.get("action_id", msg.id),
                        approved=msg.data.get("approved", False),
                        user=msg.data.get("user", ""),
                    )

            elif msg.type == ClientMessageType.CANCEL:
                logger.info("Cancel requested")
                if agent_task and not agent_task.done():
                    agent_task.cancel()

    except WebSocketDisconnect:
        if agent_task and not agent_task.done():
            agent_task.cancel()
        manager.disconnect(websocket)
        logger.info("Client disconnected")


async def _handle_user_message(
    websocket: WebSocket,
    memory: ConversationMemory,
    content: str,
    client_type: str = "web",
) -> None:
    """Process a user message through the agent loop."""
    provider = _get_provider()

    if provider is None:
        await manager.send(
            websocket,
            ServerMessage(
                type=ServerMessageType.ASSISTANT_MESSAGE_START,
                data={"conversation_id": memory.conversation_id},
            ),
        )
        await manager.send(
            websocket,
            ServerMessage(
                type=ServerMessageType.ASSISTANT_MESSAGE_DELTA,
                data={
                    "content": "LLM provider not configured. Set your API key in "
                    "the configuration (ARGUS_LLM__API_KEY environment variable) and "
                    "restart the server."
                },
            ),
        )
        await manager.send(
            websocket,
            ServerMessage(type=ServerMessageType.ASSISTANT_MESSAGE_END, data={}),
        )
        return

    # Create event callback that streams to the WebSocket
    message_started = False

    async def on_event(event_type: str, data: dict[str, Any]) -> None:
        nonlocal message_started

        if event_type == "thinking_start":
            await manager.send(
                websocket,
                ServerMessage(type=ServerMessageType.THINKING_START, data={}),
            )

        elif event_type == "thinking_end":
            await manager.send(
                websocket,
                ServerMessage(type=ServerMessageType.THINKING_END, data={}),
            )

        elif event_type == "assistant_message_delta":
            if not message_started:
                await manager.send(
                    websocket,
                    ServerMessage(
                        type=ServerMessageType.ASSISTANT_MESSAGE_START,
                        data={"conversation_id": memory.conversation_id},
                    ),
                )
                message_started = True
            await manager.send(
                websocket,
                ServerMessage(type=ServerMessageType.ASSISTANT_MESSAGE_DELTA, data=data),
            )

        elif event_type == "tool_call":
            if not message_started:
                await manager.send(
                    websocket,
                    ServerMessage(
                        type=ServerMessageType.ASSISTANT_MESSAGE_START,
                        data={"conversation_id": memory.conversation_id},
                    ),
                )
                message_started = True
            await manager.send(
                websocket,
                ServerMessage(type=ServerMessageType.TOOL_CALL, data=data),
            )

        elif event_type == "tool_result":
            await manager.send(
                websocket,
                ServerMessage(type=ServerMessageType.TOOL_RESULT, data=data),
            )

    # Ensure tools are registered (normally done in lifespan, but safety check)
    from argus_agent.tools.base import get_all_tools

    if not get_all_tools():
        from argus_agent.main import _register_all_tools

        _register_all_tools()

    # Run the agent loop
    agent = AgentLoop(
        provider=provider, memory=memory, on_event=on_event,
        client_type=client_type,
    )

    try:
        result = await agent.run(content)
    except Exception as e:
        logger.exception("Agent loop error")
        await manager.send(
            websocket,
            ServerMessage(
                type=ServerMessageType.ERROR,
                data={"message": f"Agent error: {e}"},
            ),
        )
        return

    # End the message stream
    if message_started:
        await manager.send(
            websocket,
            ServerMessage(
                type=ServerMessageType.ASSISTANT_MESSAGE_END,
                data={
                    "tokens": {
                        "prompt": result.prompt_tokens,
                        "completion": result.completion_tokens,
                    },
                    "tool_calls": result.tool_calls_made,
                    "rounds": result.rounds,
                },
            ),
        )

    # Persist conversation and messages to database
    try:
        await memory.persist_conversation(title=content[:100])
        await memory.persist_message("user", content=content)
        if result.content:
            await memory.persist_message(
                "assistant",
                content=result.content,
                token_count=result.prompt_tokens + result.completion_tokens,
            )
    except Exception:
        logger.exception("Failed to persist conversation")
