"""Agent worker process — dequeues tasks and runs agent loops independently."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from argus_agent.api.protocol import ServerMessage
from argus_agent.queue.task_queue import (
    ACTION_KEY_PREFIX,
    CANCEL_KEY_PREFIX,
    STREAM_KEY_PREFIX,
    TaskPayload,
    TaskQueue,
    TaskStatus,
)

logger = logging.getLogger("argus.queue.worker")


class RedisWSAdapter:
    """Mimics ConnectionManager.broadcast() but publishes to Redis pub/sub.

    Used inside the worker process so ActionEngine and Investigator can
    broadcast ServerMessages back to the API pod that owns the WebSocket.
    """

    def __init__(self, redis: aioredis.Redis, task_id: str) -> None:
        self._redis = redis
        self._task_id = task_id

    async def broadcast(
        self, message: ServerMessage, tenant_id: str = "default"
    ) -> None:
        """Publish a ServerMessage to the stream channel for this task."""
        payload = json.dumps({
            "event_type": "_ws_message",
            "data": message.model_dump(mode="json"),
        })
        await self._redis.publish(f"{STREAM_KEY_PREFIX}{self._task_id}", payload)

    # Stubs so it satisfies the same duck-type as ConnectionManager
    async def connect(self, *_a: Any, **_kw: Any) -> None:
        pass

    def disconnect(self, *_a: Any, **_kw: Any) -> None:
        pass

    async def send(self, *_a: Any, **_kw: Any) -> None:
        pass


class AgentWorker:
    """Standalone worker that dequeues tasks and runs agent loops.

    Intended for SaaS deployments where the API process handles only the
    WebSocket connection and this worker runs the heavy LLM + tool loop.

    Supports concurrent task processing via asyncio — since agent tasks are
    mostly I/O-bound (waiting on LLM API responses), a single worker process
    can handle multiple tasks simultaneously. Control concurrency with the
    ``max_concurrent`` parameter (default 10).
    """

    def __init__(self, redis_url: str, max_concurrent: int = 1000) -> None:
        self._redis_url = redis_url
        self._max_concurrent = max_concurrent
        self._redis: aioredis.Redis | None = None
        self._queue: TaskQueue | None = None
        self._running = False
        self._semaphore: asyncio.Semaphore | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Initialise Redis, repos, and tools, then enter the dequeue loop."""
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        self._queue = TaskQueue(self._redis)
        self._running = True
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        # Initialise DB repositories (same as SaaS lifespan in main.py)
        await self._init_repos()

        # Register tools
        from argus_agent.main import _register_all_tools

        _register_all_tools(is_sdk_only=self._settings.mode == "sdk_only")

        logger.info(
            "AgentWorker started — waiting for tasks (max_concurrent=%d)",
            self._max_concurrent,
        )
        while self._running:
            # Wait until a concurrency slot is available before dequeuing
            await self._semaphore.acquire()
            payload = await self._queue.dequeue(timeout=5)
            if payload is not None:
                task = asyncio.create_task(self._run_task(payload))
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)
            else:
                # No task available — release the semaphore slot
                self._semaphore.release()

        # Drain active tasks on shutdown
        if self._active_tasks:
            logger.info("Waiting for %d active tasks to finish...", len(self._active_tasks))
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

    async def _run_task(self, payload: TaskPayload) -> None:
        """Wrapper that processes a task and releases the semaphore slot."""
        assert self._semaphore is not None
        try:
            await self._process_task(payload)
        except Exception:
            logger.exception("Unhandled error processing task %s", payload.task_id)
        finally:
            self._semaphore.release()

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()

    # ------------------------------------------------------------------
    async def _init_repos(self) -> None:
        """Set up operational + metrics repos for the worker process."""
        from argus_agent.config import ensure_secret_key, get_settings
        from argus_agent.storage.postgres_operational import PostgresOperationalRepository
        from argus_agent.storage.repositories import (
            set_metrics_repository,
            set_operational_repository,
        )
        from argus_agent.storage.timescaledb_metrics import TimescaleDBMetricsRepository

        self._settings = get_settings()
        ensure_secret_key(self._settings)

        operational_repo = PostgresOperationalRepository()
        await operational_repo.init(self._settings.deployment.postgres_url)
        set_operational_repository(operational_repo)

        metrics_repo = TimescaleDBMetricsRepository()
        metrics_repo.init(self._settings.deployment.timescale_url)
        set_metrics_repository(metrics_repo)

        logger.info("Worker repos initialised (PG + TimescaleDB)")

    # ------------------------------------------------------------------
    async def _process_task(self, payload: TaskPayload) -> None:
        """Run the agent loop for a single task."""
        task_id = payload.task_id
        assert self._redis is not None
        assert self._queue is not None

        # 1. Set tenant context
        from argus_agent.tenancy.context import set_tenant_id

        set_tenant_id(payload.tenant_id)
        await self._queue.set_status(task_id, TaskStatus.RUNNING)

        # 2. Conversation memory — load prior messages for multi-turn context
        from argus_agent.agent.memory import ConversationMemory

        memory = ConversationMemory(conversation_id=payload.conversation_id)
        await memory.load_history()

        # 3. Build streaming callback that publishes to Redis
        redis_pub = self._redis

        async def on_event(event_type: str, data: dict[str, Any]) -> None:
            msg = json.dumps({"event_type": event_type, "data": data})
            await redis_pub.publish(f"{STREAM_KEY_PREFIX}{task_id}", msg)

        # 4. Get LLM provider
        from argus_agent.llm.registry import get_provider

        provider = get_provider()

        # 5. Build AgentLoop
        from argus_agent.agent.loop import AgentLoop

        agent = AgentLoop(
            provider=provider,
            memory=memory,
            on_event=on_event,
            client_type=payload.client_type,
            source="user_chat",
        )

        # 6. Set up cancel + action listeners
        cancel_event = asyncio.Event()
        cancel_task = asyncio.create_task(
            self._listen_for_cancel(task_id, cancel_event)
        )
        action_task = asyncio.create_task(
            self._listen_for_actions(task_id)
        )

        # 7. Run agent loop
        try:
            agent_coro = agent.run(payload.content)
            run_task = asyncio.create_task(agent_coro)

            # Wait for either completion or cancellation
            done, _pending = await asyncio.wait(
                [run_task, asyncio.create_task(cancel_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if cancel_event.is_set() and not run_task.done():
                run_task.cancel()
                try:
                    await run_task
                except asyncio.CancelledError:
                    pass
                await self._queue.set_status(task_id, TaskStatus.CANCELLED)
                await on_event("_cancelled", {})
                logger.info("Task %s cancelled", task_id)
            elif run_task.done():
                exc = run_task.exception()
                if exc is not None:
                    raise exc
                result = run_task.result()
                await self._queue.set_status(task_id, TaskStatus.COMPLETED)

                # Persist conversation — save all new messages for multi-turn context
                try:
                    await memory.persist_conversation(title=payload.content[:100])
                    # Only persist messages added during this turn (skip loaded history)
                    new_msgs = memory.messages[memory._loaded_count:]
                    for msg in new_msgs:
                        if msg.role == "system":
                            continue
                        await memory.persist_message(
                            role=msg.role,
                            content=msg.content,
                            tool_calls=msg.tool_calls if msg.tool_calls else None,
                            token_count=0,
                        )
                except Exception:
                    logger.exception("Failed to persist conversation for task %s", task_id)

                # Publish done event with token stats
                await on_event("_done", {
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "tool_calls": result.tool_calls_made,
                    "rounds": result.rounds,
                })
        except Exception as e:
            logger.exception("Task %s failed", task_id)
            await self._queue.set_status(task_id, TaskStatus.FAILED)
            await on_event("error", {"message": str(e)})
            await on_event("_done", {})
        finally:
            cancel_task.cancel()
            action_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass
            try:
                await action_task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    async def _listen_for_cancel(self, task_id: str, cancel_event: asyncio.Event) -> None:
        """Subscribe to the cancel channel; sets *cancel_event* on signal."""
        assert self._redis is not None
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(f"{CANCEL_KEY_PREFIX}{task_id}")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    cancel_event.set()
                    break
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    async def _listen_for_actions(self, task_id: str) -> None:
        """Subscribe to the action channel; routes responses to ActionEngine."""
        assert self._redis is not None
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(f"{ACTION_KEY_PREFIX}{task_id}")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        from argus_agent.main import _get_action_engine

                        engine = _get_action_engine()
                        if engine:
                            engine.handle_response(
                                action_id=data.get("action_id", ""),
                                approved=data.get("approved", False),
                                user=data.get("user", ""),
                            )
                    except Exception:
                        logger.exception("Error handling action message")
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()


async def _main() -> None:
    """Entry point for running the worker as a standalone process."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from argus_agent.config import get_settings

    settings = get_settings()
    if settings.deployment.mode != "saas":
        logger.error("AgentWorker requires SaaS mode (ARGUS_DEPLOYMENT__MODE=saas)")
        sys.exit(1)

    import os

    max_concurrent = int(os.environ.get("ARGUS_WORKER_MAX_CONCURRENT", "1000"))
    worker = AgentWorker(
        redis_url=settings.deployment.redis_url,
        max_concurrent=max_concurrent,
    )
    try:
        await worker.start()
    except KeyboardInterrupt:
        pass
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(_main())
