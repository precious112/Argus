"""Redis-backed task queue for decoupling WebSocket handlers from agent workers."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field
from redis.asyncio import Redis

logger = logging.getLogger("argus.queue")

# Redis key conventions
TASK_QUEUE_KEY = "argus:task_queue"
TASK_KEY_PREFIX = "argus:task:"
STREAM_KEY_PREFIX = "argus:stream:"
CANCEL_KEY_PREFIX = "argus:cancel:"
ACTION_KEY_PREFIX = "argus:action:"
BROADCAST_KEY_PREFIX = "argus:broadcast:"
EVENTS_KEY = "argus:events"

TASK_TTL = 3600  # 1 hour


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskPayload(BaseModel):
    """Payload for a queued agent task."""

    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    tenant_id: str
    user_id: str = ""
    conversation_id: str = ""
    content: str
    client_type: str = "web"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskQueue:
    """Redis-backed FIFO task queue for agent work items."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def enqueue(self, payload: TaskPayload) -> str:
        """Enqueue a task and return its task_id."""
        data = payload.model_dump(mode="json")
        await self._redis.lpush(TASK_QUEUE_KEY, json.dumps(data))
        await self.set_status(payload.task_id, TaskStatus.PENDING, tenant_id=payload.tenant_id)
        logger.info("Enqueued task %s for tenant %s", payload.task_id, payload.tenant_id)
        return payload.task_id

    async def dequeue(self, timeout: int = 5) -> TaskPayload | None:
        """Blocking dequeue — waits up to *timeout* seconds for a task."""
        result = await self._redis.brpop(TASK_QUEUE_KEY, timeout=timeout)
        if result is None:
            return None
        _key, raw = result
        data = json.loads(raw)
        return TaskPayload.model_validate(data)

    async def set_status(self, task_id: str, status: TaskStatus, **extra: str) -> None:
        """Update the status hash for a task."""
        key = f"{TASK_KEY_PREFIX}{task_id}"
        mapping: dict[str, str] = {"status": status.value, **extra}
        await self._redis.hset(key, mapping=mapping)
        await self._redis.expire(key, TASK_TTL)

    async def get_status(self, task_id: str) -> dict[str, str] | None:
        """Read the status hash for a task."""
        key = f"{TASK_KEY_PREFIX}{task_id}"
        data = await self._redis.hgetall(key)
        if not data:
            return None
        return data

    async def cancel(self, task_id: str) -> None:
        """Publish a cancellation signal for a running task."""
        await self._redis.publish(f"{CANCEL_KEY_PREFIX}{task_id}", "cancel")
        logger.info("Published cancel for task %s", task_id)
