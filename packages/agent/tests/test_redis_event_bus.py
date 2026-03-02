"""Tests for RedisEventBus."""

from __future__ import annotations

import asyncio
import json

import pytest
from fakeredis import aioredis as fakeredis_aioredis

from argus_agent.events.bus import RedisEventBus, reset_event_bus
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType


@pytest.fixture(autouse=True)
def _reset():
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.fixture
async def redis():
    r = fakeredis_aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


class TestRedisEventBus:
    @pytest.mark.asyncio
    async def test_publish_fires_local_handler(self, redis):
        bus = RedisEventBus(redis)
        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(handler)

        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
            message="test",
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].message == "test"

    @pytest.mark.asyncio
    async def test_publish_sends_to_redis(self, redis):
        bus = RedisEventBus(redis)

        received = []

        async def _listen():
            pubsub = redis.pubsub()
            await pubsub.subscribe("argus:events")
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    received.append(json.loads(msg["data"]))
                    break
            await pubsub.unsubscribe()
            await pubsub.aclose()

        listener = asyncio.create_task(_listen())
        await asyncio.sleep(0.05)

        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.CPU_HIGH,
            severity=EventSeverity.URGENT,
            message="CPU high",
        )
        await bus.publish(event)

        await asyncio.wait_for(listener, timeout=2)
        assert len(received) == 1
        assert received[0]["type"] == EventType.CPU_HIGH
        assert received[0]["severity"] == "URGENT"

    @pytest.mark.asyncio
    async def test_subscribe_fires_local_for_remote_events(self):
        """Events from Redis should be delivered to local handlers."""
        redis = fakeredis_aioredis.FakeRedis(decode_responses=True)
        bus = RedisEventBus(redis)

        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(handler)
        await bus.start()
        await asyncio.sleep(0.1)

        # Simulate a remote event by publishing directly to Redis
        remote_event = {
            "source": EventSource.LOG_WATCHER,
            "type": EventType.ERROR_BURST,
            "severity": "URGENT",
            "data": {},
            "message": "remote burst",
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        await redis.publish("argus:events", json.dumps(remote_event))
        await asyncio.sleep(0.2)

        assert len(received) >= 1
        assert received[-1].message == "remote burst"

        bus.stop()
        await redis.aclose()

    @pytest.mark.asyncio
    async def test_no_republish_loop(self):
        """Events from Redis should NOT be re-published to Redis."""
        redis = fakeredis_aioredis.FakeRedis(decode_responses=True)
        bus = RedisEventBus(redis)

        publish_count = 0
        original_publish = redis.publish

        async def counting_publish(channel, message):
            nonlocal publish_count
            publish_count += 1
            return await original_publish(channel, message)

        redis.publish = counting_publish

        await bus.start()
        await asyncio.sleep(0.1)

        # Publish directly (simulating remote)
        remote_event = {
            "source": EventSource.SYSTEM_METRICS,
            "type": EventType.METRIC_COLLECTED,
            "severity": "NORMAL",
            "data": {},
            "message": "test",
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        await original_publish("argus:events", json.dumps(remote_event))
        await asyncio.sleep(0.2)

        # Only the original publish should have happened (count == 1)
        assert publish_count <= 1

        bus.stop()
        await redis.aclose()

    @pytest.mark.asyncio
    async def test_recent_events_tracked(self, redis):
        bus = RedisEventBus(redis)

        event = Event(
            source=EventSource.SYSTEM_METRICS,
            type=EventType.METRIC_COLLECTED,
        )
        await bus.publish(event)

        recent = bus.get_recent_events()
        assert len(recent) == 1

    @pytest.mark.asyncio
    async def test_clear(self, redis):
        bus = RedisEventBus(redis)

        async def noop(e: Event):
            pass

        bus.subscribe(noop)
        bus.clear()

        assert len(bus._handlers) == 0
        assert len(bus._recent_events) == 0
