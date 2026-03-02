"""WebSocket chat handler for Argus agent server."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import redis.asyncio as aioredis
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
    """Manage active WebSocket connections, keyed by tenant_id."""

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, tenant_id: str = "default") -> None:
        await websocket.accept()
        if tenant_id not in self.active_connections:
            self.active_connections[tenant_id] = []
        self.active_connections[tenant_id].append(websocket)

    def disconnect(self, websocket: WebSocket, tenant_id: str = "default") -> None:
        conns = self.active_connections.get(tenant_id, [])
        if websocket in conns:
            conns.remove(websocket)
            if not conns:
                self.active_connections.pop(tenant_id, None)

    async def send(self, websocket: WebSocket, message: ServerMessage) -> None:
        await websocket.send_json(message.model_dump(mode="json"))

    async def broadcast(self, message: ServerMessage, tenant_id: str = "default") -> None:
        for connection in self.active_connections.get(tenant_id, []):
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
    # Verify JWT from cookie before accepting the connection
    token = websocket.cookies.get("argus_token", "")
    if token:
        try:
            from argus_agent.auth.jwt import decode_access_token

            payload = decode_access_token(token)
        except Exception:
            await websocket.close(code=4001, reason="Invalid or expired token")
            return
    else:
        await websocket.close(code=4001, reason="Authentication required")
        return

    tenant_id = payload.get("tenant_id", "default")

    # Set tenant context for this WebSocket connection
    from argus_agent.tenancy.context import set_tenant_id

    set_tenant_id(tenant_id)

    await manager.connect(websocket, tenant_id)
    client_type = client if client in ("cli", "web") else "web"

    # In SaaS mode, delegate to the thin handler that enqueues to Redis
    from argus_agent.config import get_settings as _get_ws_settings

    if _get_ws_settings().deployment.mode == "saas":
        try:
            await _handle_ws_saas(websocket, tenant_id, payload, client_type)
        except WebSocketDisconnect:
            manager.disconnect(websocket, tenant_id)
            logger.info("SaaS client disconnected")
        return

    # --- Self-hosted path (unchanged) ---

    # Send connected message with initial system status
    from argus_agent.collectors.system_metrics import get_system_snapshot

    await manager.send(
        websocket,
        ServerMessage(
            type=ServerMessageType.CONNECTED,
            data={"message": "Connected to Argus agent"},
        ),
    )

    # Send initial system status (always, so frontend knows the mode)
    from argus_agent.config import get_settings

    settings = get_settings()
    snapshot = get_system_snapshot()
    status_data: dict[str, Any] = {**snapshot, "mode": settings.mode}
    await manager.send(
        websocket,
        ServerMessage(
            type=ServerMessageType.SYSTEM_STATUS,
            data=status_data,
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
        manager.disconnect(websocket, tenant_id)
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
        source="user_chat",
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


# ---------------------------------------------------------------------------
# SaaS thin handler — enqueues tasks to Redis, relays stream events
# ---------------------------------------------------------------------------


async def _handle_ws_saas(
    websocket: WebSocket,
    tenant_id: str,
    jwt_payload: dict[str, Any],
    client_type: str,
) -> None:
    """SaaS-mode WebSocket handler.

    Instead of running the agent loop in-process, tasks are enqueued into
    a Redis list and a separate ``AgentWorker`` process picks them up.
    Streaming events are relayed back via Redis pub/sub.
    """
    from argus_agent.config import get_settings
    from argus_agent.queue.task_queue import (
        ACTION_KEY_PREFIX,
        TaskPayload,
        TaskQueue,
    )

    settings = get_settings()
    redis = aioredis.from_url(settings.deployment.redis_url, decode_responses=True)
    queue = TaskQueue(redis)

    # Send initial handshake messages
    from argus_agent.collectors.system_metrics import get_system_snapshot

    await manager.send(
        websocket,
        ServerMessage(
            type=ServerMessageType.CONNECTED,
            data={"message": "Connected to Argus agent"},
        ),
    )
    snapshot = get_system_snapshot()
    status_data: dict[str, Any] = {**snapshot, "mode": settings.mode}
    await manager.send(
        websocket,
        ServerMessage(type=ServerMessageType.SYSTEM_STATUS, data=status_data),
    )

    active_task_id: str | None = None
    relay_task: asyncio.Task | None = None  # type: ignore[type-arg]

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

                if relay_task and not relay_task.done():
                    await manager.send(
                        websocket,
                        ServerMessage(
                            type=ServerMessageType.ERROR,
                            data={"message": "Agent is busy, please wait."},
                        ),
                    )
                    continue

                payload = TaskPayload(
                    tenant_id=tenant_id,
                    user_id=jwt_payload.get("sub", ""),
                    conversation_id=str(uuid.uuid4()),
                    content=content,
                    client_type=client_type,
                )
                await queue.enqueue(payload)
                active_task_id = payload.task_id

                relay_task = asyncio.create_task(
                    _relay_stream(
                        websocket,
                        redis,
                        active_task_id,
                        payload.conversation_id,
                    )
                )

            elif msg.type == ClientMessageType.ACTION_RESPONSE:
                if active_task_id:
                    data = json.dumps({
                        "action_id": msg.data.get("action_id", msg.id),
                        "approved": msg.data.get("approved", False),
                        "user": msg.data.get("user", ""),
                    })
                    await redis.publish(
                        f"{ACTION_KEY_PREFIX}{active_task_id}", data
                    )

            elif msg.type == ClientMessageType.CANCEL:
                if active_task_id:
                    await queue.cancel(active_task_id)

    finally:
        # On disconnect: stop relay, but do NOT cancel the worker task —
        # it will persist results to DB independently.
        if relay_task and not relay_task.done():
            relay_task.cancel()
            try:
                await relay_task
            except asyncio.CancelledError:
                pass
        manager.disconnect(websocket, tenant_id)
        await redis.aclose()


async def _relay_stream(
    websocket: WebSocket,
    redis: aioredis.Redis,
    task_id: str,
    conversation_id: str,
) -> None:
    """Subscribe to the worker's stream channel and forward events to the WS."""
    from argus_agent.queue.task_queue import STREAM_KEY_PREFIX

    pubsub = redis.pubsub()
    message_started = False

    try:
        await pubsub.subscribe(f"{STREAM_KEY_PREFIX}{task_id}")
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                payload = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue

            event_type = payload.get("event_type", "")
            data = payload.get("data", {})

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
                            data={"conversation_id": conversation_id},
                        ),
                    )
                    message_started = True
                await manager.send(
                    websocket,
                    ServerMessage(
                        type=ServerMessageType.ASSISTANT_MESSAGE_DELTA, data=data
                    ),
                )

            elif event_type == "tool_call":
                if not message_started:
                    await manager.send(
                        websocket,
                        ServerMessage(
                            type=ServerMessageType.ASSISTANT_MESSAGE_START,
                            data={"conversation_id": conversation_id},
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

            elif event_type == "_ws_message":
                # Forward as-is (ACTION_REQUEST, etc.)
                try:
                    srv = ServerMessage.model_validate(data)
                    await manager.send(websocket, srv)
                except Exception:
                    logger.warning("Failed to forward _ws_message")

            elif event_type == "_done":
                if message_started:
                    await manager.send(
                        websocket,
                        ServerMessage(
                            type=ServerMessageType.ASSISTANT_MESSAGE_END,
                            data={
                                "tokens": {
                                    "prompt": data.get("prompt_tokens", 0),
                                    "completion": data.get("completion_tokens", 0),
                                },
                                "tool_calls": data.get("tool_calls", 0),
                                "rounds": data.get("rounds", 0),
                            },
                        ),
                    )
                break

            elif event_type in ("_cancelled", "error"):
                default_msg = "Task cancelled" if event_type == "_cancelled" else "Agent error"
                err_msg = data.get("message", default_msg)
                await manager.send(
                    websocket,
                    ServerMessage(
                        type=ServerMessageType.ERROR,
                        data={"message": err_msg},
                    ),
                )
                break

    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
