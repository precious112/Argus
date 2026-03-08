"""Tests for Redis-backed task queue."""

from __future__ import annotations

import asyncio

import pytest
from fakeredis import aioredis as fakeredis_aioredis

from argus_agent.queue.task_queue import TaskPayload, TaskQueue, TaskStatus


@pytest.fixture
async def redis():
    r = fakeredis_aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
def queue(redis):
    return TaskQueue(redis)


class TestTaskQueue:
    @pytest.mark.asyncio
    async def test_enqueue_dequeue_roundtrip(self, queue):
        payload = TaskPayload(tenant_id="t1", content="hello")
        task_id = await queue.enqueue(payload)

        result = await queue.dequeue(timeout=1)
        assert result is not None
        assert result.task_id == task_id
        assert result.tenant_id == "t1"
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_fifo_order(self, queue):
        p1 = TaskPayload(tenant_id="t1", content="first")
        p2 = TaskPayload(tenant_id="t1", content="second")
        p3 = TaskPayload(tenant_id="t1", content="third")

        await queue.enqueue(p1)
        await queue.enqueue(p2)
        await queue.enqueue(p3)

        r1 = await queue.dequeue(timeout=1)
        r2 = await queue.dequeue(timeout=1)
        r3 = await queue.dequeue(timeout=1)

        assert r1 is not None and r1.content == "first"
        assert r2 is not None and r2.content == "second"
        assert r3 is not None and r3.content == "third"

    @pytest.mark.asyncio
    async def test_status_tracking(self, queue):
        payload = TaskPayload(tenant_id="t1", content="test")
        task_id = await queue.enqueue(payload)

        status = await queue.get_status(task_id)
        assert status is not None
        assert status["status"] == TaskStatus.PENDING

        await queue.set_status(task_id, TaskStatus.RUNNING)
        status = await queue.get_status(task_id)
        assert status is not None
        assert status["status"] == TaskStatus.RUNNING

        await queue.set_status(task_id, TaskStatus.COMPLETED)
        status = await queue.get_status(task_id)
        assert status is not None
        assert status["status"] == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_empty_dequeue_returns_none(self, queue):
        result = await queue.dequeue(timeout=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_publishes(self, queue, redis):
        """cancel() should publish to the cancel channel."""
        payload = TaskPayload(tenant_id="t1", content="test")
        task_id = await queue.enqueue(payload)

        # Use a listener task to capture the published message
        received = []

        async def _listen():
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"argus:cancel:{task_id}")
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    received.append(msg["data"])
                    break
            await pubsub.unsubscribe()
            await pubsub.aclose()

        listener = asyncio.create_task(_listen())
        await asyncio.sleep(0.05)  # let subscription establish

        await queue.cancel(task_id)
        await asyncio.wait_for(listener, timeout=2)

        assert len(received) == 1
        assert received[0] == "cancel"

    @pytest.mark.asyncio
    async def test_status_with_extra_fields(self, queue):
        payload = TaskPayload(tenant_id="t1", content="test")
        task_id = await queue.enqueue(payload)

        await queue.set_status(task_id, TaskStatus.RUNNING, tenant_id="t1")
        status = await queue.get_status(task_id)
        assert status is not None
        assert status["tenant_id"] == "t1"

    @pytest.mark.asyncio
    async def test_nonexistent_status(self, queue):
        status = await queue.get_status("nonexistent")
        assert status is None

    @pytest.mark.asyncio
    async def test_payload_defaults(self):
        p = TaskPayload(tenant_id="t1", content="hi")
        assert p.task_id  # auto-generated
        assert p.client_type == "web"
        assert p.user_id == ""
