"""Tests for the periodic scheduler."""

from __future__ import annotations

import asyncio

import pytest

from argus_agent.config import reset_settings
from argus_agent.events.bus import reset_event_bus
from argus_agent.scheduler.scheduler import Scheduler


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    reset_event_bus()
    yield
    reset_settings()
    reset_event_bus()


class TestScheduler:
    @pytest.mark.asyncio
    async def test_register_and_start(self):
        scheduler = Scheduler()
        calls = []

        async def task():
            calls.append(1)

        scheduler.register("test", task, interval_seconds=0.1)
        await scheduler.start()
        assert scheduler.is_running

        await asyncio.sleep(0.3)
        await scheduler.stop()
        assert not scheduler.is_running
        assert len(calls) >= 1

    @pytest.mark.asyncio
    async def test_disabled_task(self):
        scheduler = Scheduler()
        calls = []

        async def task():
            calls.append(1)

        scheduler.register("test", task, interval_seconds=0.1, enabled=False)
        await scheduler.start()
        await asyncio.sleep(0.3)
        await scheduler.stop()
        assert len(calls) == 0

    @pytest.mark.asyncio
    async def test_get_status(self):
        scheduler = Scheduler()

        async def noop():
            pass

        scheduler.register("task_a", noop, interval_seconds=300)
        scheduler.register("task_b", noop, interval_seconds=600, enabled=False)

        status = scheduler.get_status()
        assert len(status) == 2
        assert status[0]["name"] == "task_a"
        assert status[0]["enabled"] is True
        assert status[1]["name"] == "task_b"
        assert status[1]["enabled"] is False

    @pytest.mark.asyncio
    async def test_error_in_task_doesnt_stop_scheduler(self):
        scheduler = Scheduler()
        calls = []

        async def failing_task():
            calls.append(1)
            raise ValueError("boom")

        scheduler.register("fail", failing_task, interval_seconds=0.1)
        await scheduler.start()
        await asyncio.sleep(0.4)
        await scheduler.stop()

        # Should have run multiple times despite errors
        assert len(calls) >= 2

    @pytest.mark.asyncio
    async def test_no_double_start(self):
        scheduler = Scheduler()

        async def noop():
            pass

        scheduler.register("test", noop, interval_seconds=999)
        await scheduler.start()
        await scheduler.start()  # Should not fail
        assert scheduler.is_running
        await scheduler.stop()
