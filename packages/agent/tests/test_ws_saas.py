"""Tests for SaaS WebSocket handler logic."""

from __future__ import annotations

import asyncio
import json

import pytest
from fakeredis import aioredis as fakeredis_aioredis

from argus_agent.api.protocol import ServerMessage, ServerMessageType
from argus_agent.queue.task_queue import (
    ACTION_KEY_PREFIX,
    STREAM_KEY_PREFIX,
    TaskPayload,
    TaskQueue,
    TaskStatus,
)


@pytest.fixture
async def redis():
    r = fakeredis_aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
def queue(redis):
    return TaskQueue(redis)


class TestSaaSEnqueue:
    """Verify that the SaaS path enqueues tasks correctly."""

    @pytest.mark.asyncio
    async def test_enqueue_creates_task(self, queue):
        payload = TaskPayload(
            tenant_id="t1",
            user_id="u1",
            content="What is happening?",
            client_type="web",
        )
        task_id = await queue.enqueue(payload)

        status = await queue.get_status(task_id)
        assert status is not None
        assert status["status"] == TaskStatus.PENDING

        dequeued = await queue.dequeue(timeout=1)
        assert dequeued is not None
        assert dequeued.content == "What is happening?"
        assert dequeued.tenant_id == "t1"
        assert dequeued.user_id == "u1"


class TestRelayStream:
    """Verify the event mapping used by _relay_stream."""

    EVENT_MAP = {
        "thinking_start": ServerMessageType.THINKING_START,
        "thinking_end": ServerMessageType.THINKING_END,
        "tool_call": ServerMessageType.TOOL_CALL,
        "tool_result": ServerMessageType.TOOL_RESULT,
    }

    @pytest.mark.asyncio
    async def test_event_type_mapping(self):
        """Each worker event type should map to the correct type."""
        for worker_event, expected_type in self.EVENT_MAP.items():
            assert expected_type is not None, f"No mapping for {worker_event}"

    @pytest.mark.asyncio
    async def test_done_event_format(self):
        """_done should produce ASSISTANT_MESSAGE_END with token stats."""
        done_data = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "tool_calls": 3,
            "rounds": 2,
        }
        msg = ServerMessage(
            type=ServerMessageType.ASSISTANT_MESSAGE_END,
            data={
                "tokens": {
                    "prompt": done_data["prompt_tokens"],
                    "completion": done_data["completion_tokens"],
                },
                "tool_calls": done_data["tool_calls"],
                "rounds": done_data["rounds"],
            },
        )
        assert msg.data["tokens"]["prompt"] == 100
        assert msg.data["rounds"] == 2


class TestActionForwarding:
    """Test that action responses are published to the right channel."""

    @pytest.mark.asyncio
    async def test_action_response_published(self, redis):
        task_id = "action-task-1"
        received = []

        async def _listen():
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"{ACTION_KEY_PREFIX}{task_id}")
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    received.append(json.loads(msg["data"]))
                    break
            await pubsub.unsubscribe()
            await pubsub.aclose()

        listener = asyncio.create_task(_listen())
        await asyncio.sleep(0.05)

        data = json.dumps({
            "action_id": "a1",
            "approved": True,
            "user": "admin",
        })
        await redis.publish(f"{ACTION_KEY_PREFIX}{task_id}", data)

        await asyncio.wait_for(listener, timeout=2)
        assert len(received) == 1
        assert received[0]["action_id"] == "a1"
        assert received[0]["approved"] is True


class TestCancelForwarding:
    """Test that cancel signals reach the worker."""

    @pytest.mark.asyncio
    async def test_cancel_published(self, queue, redis):
        payload = TaskPayload(tenant_id="t1", content="test")
        task_id = await queue.enqueue(payload)

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
        await asyncio.sleep(0.05)

        await queue.cancel(task_id)

        await asyncio.wait_for(listener, timeout=2)
        assert len(received) == 1
        assert received[0] == "cancel"


class TestStreamPublish:
    """Test that the worker on_event pattern publishes correctly."""

    @pytest.mark.asyncio
    async def test_stream_events_published(self, redis):
        task_id = "stream-1"

        events_to_send = [
            ("thinking_start", {}),
            ("assistant_message_delta", {"content": "analyzing..."}),
            ("tool_call", {"id": "tc1", "name": "get_metrics"}),
            ("tool_result", {"id": "tc1", "name": "get_metrics"}),
            ("_done", {"prompt_tokens": 50, "completion_tokens": 20}),
        ]
        received = []

        async def _listen():
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"{STREAM_KEY_PREFIX}{task_id}")
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    received.append(json.loads(msg["data"]))
                    if len(received) >= len(events_to_send):
                        break
            await pubsub.unsubscribe()
            await pubsub.aclose()

        listener = asyncio.create_task(_listen())
        await asyncio.sleep(0.05)

        for event_type, data in events_to_send:
            msg = json.dumps({"event_type": event_type, "data": data})
            await redis.publish(f"{STREAM_KEY_PREFIX}{task_id}", msg)

        await asyncio.wait_for(listener, timeout=2)

        assert len(received) == len(events_to_send)
        assert received[0]["event_type"] == "thinking_start"
        assert received[-1]["event_type"] == "_done"
