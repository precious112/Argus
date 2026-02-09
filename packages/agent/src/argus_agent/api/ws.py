"""WebSocket chat handler for Argus agent server."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket endpoint for chat communication."""
    await manager.connect(websocket)

    # Send connected message
    await manager.send(
        websocket,
        ServerMessage(
            type=ServerMessageType.CONNECTED,
            data={"message": "Connected to Argus agent"},
        ),
    )

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
                # Phase 0: echo back a placeholder response
                content = msg.data.get("content", "")
                await manager.send(
                    websocket,
                    ServerMessage(
                        type=ServerMessageType.ASSISTANT_MESSAGE_START,
                        data={"conversation_id": msg.id},
                    ),
                )
                await manager.send(
                    websocket,
                    ServerMessage(
                        type=ServerMessageType.ASSISTANT_MESSAGE_DELTA,
                        data={"content": f"Agent not yet implemented. You said: {content}"},
                    ),
                )
                await manager.send(
                    websocket,
                    ServerMessage(
                        type=ServerMessageType.ASSISTANT_MESSAGE_END,
                        data={},
                    ),
                )
            elif msg.type == ClientMessageType.ACTION_RESPONSE:
                logger.info("Action response received: %s", msg.data)
            elif msg.type == ClientMessageType.CANCEL:
                logger.info("Cancel requested")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client disconnected")
