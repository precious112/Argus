"""Distributed ConnectionManager — wraps local manager with Redis pub/sub."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from redis.asyncio import Redis

from argus_agent.api.protocol import ServerMessage
from argus_agent.api.ws import ConnectionManager
from argus_agent.queue.task_queue import BROADCAST_KEY_PREFIX

logger = logging.getLogger("argus.queue.distributed")


class DistributedConnectionManager:
    """Cross-pod broadcast layer on top of the local ConnectionManager.

    When ``broadcast()`` is called the message is published to
    ``argus:broadcast:{tenant_id}`` on Redis.  A background subscription
    loop picks up messages from Redis and forwards them to the local
    manager so that WebSocket clients on every API pod receive the update.
    """

    def __init__(self, local: ConnectionManager, redis: Redis) -> None:
        self._local = local
        self._redis = redis
        self._sub_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._publishing = False  # Guard against rebroadcast loops

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._sub_task = asyncio.create_task(self._subscribe_loop())
        logger.info("DistributedConnectionManager started")

    async def stop(self) -> None:
        if self._sub_task:
            self._sub_task.cancel()
            try:
                await self._sub_task
            except asyncio.CancelledError:
                pass
        logger.info("DistributedConnectionManager stopped")

    # -- public API (duck-types with ConnectionManager) --------------------

    async def connect(self, websocket: Any, tenant_id: str = "default") -> None:
        await self._local.connect(websocket, tenant_id)

    def disconnect(self, websocket: Any, tenant_id: str = "default") -> None:
        self._local.disconnect(websocket, tenant_id)

    async def send(self, websocket: Any, message: ServerMessage) -> None:
        await self._local.send(websocket, message)

    async def broadcast(self, message: ServerMessage, tenant_id: str = "default") -> None:
        """Publish to Redis — the subscribe loop will deliver locally."""
        payload = json.dumps({
            "tenant_id": tenant_id,
            "message": message.model_dump(mode="json"),
        })
        await self._redis.publish(f"{BROADCAST_KEY_PREFIX}{tenant_id}", payload)

    # -- subscription loop -------------------------------------------------

    async def _subscribe_loop(self) -> None:
        pubsub = self._redis.pubsub()
        try:
            await pubsub.psubscribe(f"{BROADCAST_KEY_PREFIX}*")
            async for message in pubsub.listen():
                if message["type"] not in ("pmessage",):
                    continue
                try:
                    data = json.loads(message["data"])
                    tenant_id = data.get("tenant_id", "default")
                    srv = ServerMessage.model_validate(data["message"])
                    # Deliver locally without re-publishing to Redis
                    await self._local.broadcast(srv, tenant_id)
                except Exception:
                    logger.debug("Error in distributed broadcast relay", exc_info=True)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.punsubscribe()
            await pubsub.aclose()
