"""Tests for AgentWorker and RedisWSAdapter."""

from __future__ import annotations

import asyncio
import json

import pytest
from fakeredis import aioredis as fakeredis_aioredis

from argus_agent.api.protocol import ServerMessage, ServerMessageType
from argus_agent.queue.task_queue import STREAM_KEY_PREFIX, TaskPayload, TaskQueue, TaskStatus
from argus_agent.queue.worker import RedisWSAdapter


@pytest.fixture
async def redis():
    r = fakeredis_aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


class TestRedisWSAdapter:
    @pytest.mark.asyncio
    async def test_broadcast_publishes_to_stream(self, redis):
        adapter = RedisWSAdapter(redis, task_id="test-task-1")

        received = []

        async def _listen():
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"{STREAM_KEY_PREFIX}test-task-1")
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    received.append(json.loads(msg["data"]))
                    break
            await pubsub.unsubscribe()
            await pubsub.aclose()

        listener = asyncio.create_task(_listen())
        await asyncio.sleep(0.05)

        msg = ServerMessage(
            type=ServerMessageType.ACTION_REQUEST,
            data={"id": "a1", "tool": "run_command"},
        )
        await adapter.broadcast(msg, tenant_id="t1")

        await asyncio.wait_for(listener, timeout=2)
        assert len(received) == 1
        assert received[0]["event_type"] == "_ws_message"
        assert received[0]["data"]["type"] == "action_request"

    @pytest.mark.asyncio
    async def test_stubs_do_not_raise(self, redis):
        adapter = RedisWSAdapter(redis, task_id="t1")
        await adapter.connect()
        adapter.disconnect()
        await adapter.send()


class TestWorkerStatusTransitions:
    """Test the status lifecycle without running a full AgentWorker."""

    @pytest.mark.asyncio
    async def test_pending_to_running(self, redis):
        queue = TaskQueue(redis)
        payload = TaskPayload(tenant_id="t1", content="test")
        await queue.enqueue(payload)

        status = await queue.get_status(payload.task_id)
        assert status is not None
        assert status["status"] == TaskStatus.PENDING

        await queue.set_status(payload.task_id, TaskStatus.RUNNING)
        status = await queue.get_status(payload.task_id)
        assert status is not None
        assert status["status"] == TaskStatus.RUNNING

    @pytest.mark.asyncio
    async def test_running_to_completed(self, redis):
        queue = TaskQueue(redis)
        payload = TaskPayload(tenant_id="t1", content="test")
        await queue.enqueue(payload)
        await queue.set_status(payload.task_id, TaskStatus.RUNNING)
        await queue.set_status(payload.task_id, TaskStatus.COMPLETED)

        status = await queue.get_status(payload.task_id)
        assert status is not None
        assert status["status"] == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_running_to_cancelled(self, redis):
        queue = TaskQueue(redis)
        payload = TaskPayload(tenant_id="t1", content="test")
        await queue.enqueue(payload)
        await queue.set_status(payload.task_id, TaskStatus.RUNNING)
        await queue.set_status(payload.task_id, TaskStatus.CANCELLED)

        status = await queue.get_status(payload.task_id)
        assert status is not None
        assert status["status"] == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_running_to_failed(self, redis):
        queue = TaskQueue(redis)
        payload = TaskPayload(tenant_id="t1", content="test")
        await queue.enqueue(payload)
        await queue.set_status(payload.task_id, TaskStatus.RUNNING)
        await queue.set_status(payload.task_id, TaskStatus.FAILED)

        status = await queue.get_status(payload.task_id)
        assert status is not None
        assert status["status"] == TaskStatus.FAILED


class TestOnEventCallback:
    """Verify the on_event pattern used by the worker publishes to Redis."""

    @pytest.mark.asyncio
    async def test_on_event_publishes_stream(self, redis):
        task_id = "evt-test"
        received = []

        async def _listen():
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"{STREAM_KEY_PREFIX}{task_id}")
            count = 0
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    received.append(json.loads(msg["data"]))
                    count += 1
                    if count >= 3:
                        break
            await pubsub.unsubscribe()
            await pubsub.aclose()

        listener = asyncio.create_task(_listen())
        await asyncio.sleep(0.05)

        # Simulate the callback the worker builds
        async def on_event(event_type: str, data: dict) -> None:
            msg = json.dumps({"event_type": event_type, "data": data})
            await redis.publish(f"{STREAM_KEY_PREFIX}{task_id}", msg)

        await on_event("thinking_start", {})
        await on_event("assistant_message_delta", {"content": "hello"})
        await on_event("_done", {"prompt_tokens": 10, "completion_tokens": 5})

        await asyncio.wait_for(listener, timeout=2)

        assert len(received) == 3
        assert received[0]["event_type"] == "thinking_start"
        assert received[1]["event_type"] == "assistant_message_delta"
        assert received[1]["data"]["content"] == "hello"
        assert received[2]["event_type"] == "_done"
