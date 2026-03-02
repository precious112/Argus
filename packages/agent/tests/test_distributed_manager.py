"""Tests for DistributedConnectionManager."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fakeredis import aioredis as fakeredis_aioredis

from argus_agent.api.protocol import ServerMessage, ServerMessageType
from argus_agent.queue.distributed_manager import DistributedConnectionManager
from argus_agent.queue.task_queue import BROADCAST_KEY_PREFIX


@pytest.fixture
async def redis():
    r = fakeredis_aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


def _make_local_manager():
    m = MagicMock()
    m.connect = AsyncMock()
    m.disconnect = MagicMock()
    m.send = AsyncMock()
    m.broadcast = AsyncMock()
    return m


class TestDistributedConnectionManager:
    @pytest.mark.asyncio
    async def test_broadcast_publishes_to_redis(self, redis):
        local = _make_local_manager()
        mgr = DistributedConnectionManager(local, redis)

        received = []

        async def _listen():
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"{BROADCAST_KEY_PREFIX}tenant-1")
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    received.append(json.loads(msg["data"]))
                    break
            await pubsub.unsubscribe()
            await pubsub.aclose()

        listener = asyncio.create_task(_listen())
        await asyncio.sleep(0.05)

        msg = ServerMessage(type=ServerMessageType.ALERT, data={"id": "a1"})
        await mgr.broadcast(msg, tenant_id="tenant-1")

        await asyncio.wait_for(listener, timeout=2)
        assert len(received) == 1
        assert received[0]["tenant_id"] == "tenant-1"
        assert received[0]["message"]["type"] == "alert"

    @pytest.mark.asyncio
    async def test_subscribe_delivers_locally(self):
        """The subscription loop should forward Redis messages to local."""
        redis = fakeredis_aioredis.FakeRedis(decode_responses=True)
        local = _make_local_manager()
        mgr = DistributedConnectionManager(local, redis)

        await mgr.start()
        await asyncio.sleep(0.1)

        # Publish directly to Redis (simulating another pod)
        msg = ServerMessage(type=ServerMessageType.ALERT, data={"id": "x1"})
        payload = json.dumps({
            "tenant_id": "t2",
            "message": msg.model_dump(mode="json"),
        })
        await redis.publish(f"{BROADCAST_KEY_PREFIX}t2", payload)
        await asyncio.sleep(0.2)

        assert local.broadcast.called

        await mgr.stop()
        await redis.aclose()

    @pytest.mark.asyncio
    async def test_connect_disconnect_delegate(self, redis):
        local = _make_local_manager()
        mgr = DistributedConnectionManager(local, redis)

        ws_mock = MagicMock()
        await mgr.connect(ws_mock, "t1")
        local.connect.assert_called_once_with(ws_mock, "t1")

        mgr.disconnect(ws_mock, "t1")
        local.disconnect.assert_called_once_with(ws_mock, "t1")

    @pytest.mark.asyncio
    async def test_send_delegates(self, redis):
        local = _make_local_manager()
        mgr = DistributedConnectionManager(local, redis)

        ws_mock = MagicMock()
        msg = ServerMessage(type=ServerMessageType.PONG)
        await mgr.send(ws_mock, msg)
        local.send.assert_called_once_with(ws_mock, msg)

    @pytest.mark.asyncio
    async def test_start_stop(self, redis):
        local = _make_local_manager()
        mgr = DistributedConnectionManager(local, redis)
        await mgr.start()
        assert mgr._sub_task is not None
        await mgr.stop()
        assert mgr._sub_task.cancelled() or mgr._sub_task.done()
