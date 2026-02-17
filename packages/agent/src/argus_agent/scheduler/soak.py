"""Soak test runner — drives real system activity to validate the notification pipeline.

Triggers real collector → event bus → alert engine → notification channel flow.
No synthetic data injection: all telemetry goes through the standard ingest path.

Enable with:
    ARGUS_SOAK_ENABLED=true
    ARGUS_SOAK_APPS='[{"path":"examples/python-fastapi",...}]'
"""

from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import random
import signal
import stat
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("argus.soak")

# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------

ENDPOINTS = [
    ("/", 40),
    ("/error", 20),
    ("/slow", 15),
    ("/chain", 10),
    ("/users", 5),
    ("/checkout", 5),
    ("/multi-error", 5),
]

_TOTAL_WEIGHT = sum(w for _, w in ENDPOINTS)


@dataclass
class SoakAppConfig:
    """Configuration for a single example app subprocess."""

    path: str
    cmd: str
    port: int
    env: dict[str, str] = field(default_factory=dict)


def parse_soak_apps() -> list[SoakAppConfig]:
    """Parse ARGUS_SOAK_APPS env var (JSON list) into config objects."""
    raw = os.environ.get("ARGUS_SOAK_APPS", "")
    if not raw:
        return []
    try:
        items: list[dict[str, Any]] = json.loads(raw)
        return [
            SoakAppConfig(
                path=item["path"],
                cmd=item["cmd"],
                port=item["port"],
                env=item.get("env", {}),
            )
            for item in items
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.exception("Failed to parse ARGUS_SOAK_APPS")
        return []


def _pick_endpoint() -> str:
    """Weighted-random endpoint selection."""
    r = random.randint(1, _TOTAL_WEIGHT)
    cumulative = 0
    for ep, weight in ENDPOINTS:
        cumulative += weight
        if r <= cumulative:
            return ep
    return "/"


# ---------------------------------------------------------------------------
#  Activity helpers
# ---------------------------------------------------------------------------


def _cpu_stress(duration_seconds: float) -> None:
    """Run a CPU-intensive loop on all cores for *duration_seconds*."""
    end = time.monotonic() + duration_seconds

    def _burn() -> None:
        while time.monotonic() < end:
            _ = sum(i * i for i in range(10_000))

    cores = multiprocessing.cpu_count() or 1
    procs: list[multiprocessing.Process] = []
    for _ in range(cores):
        p = multiprocessing.Process(target=_burn, daemon=True)
        p.start()
        procs.append(p)

    # Wait for them to finish (bounded by duration)
    for p in procs:
        p.join(timeout=duration_seconds + 5)
        if p.is_alive():
            p.terminate()


def _memory_stress(duration_seconds: float, target_fraction: float = 0.7) -> None:
    """Allocate ~target_fraction of RAM for *duration_seconds*.

    Uses a bytearray to actually commit the pages.
    """
    try:
        import psutil

        total = psutil.virtual_memory().total
    except Exception:
        total = 8 * 1024**3  # fallback 8 GB

    alloc_bytes = int(total * target_fraction)
    logger.info("Memory stress: allocating ~%.0f MB for %.0fs", alloc_bytes / 1e6, duration_seconds)
    try:
        blob = bytearray(alloc_bytes)
        # Touch pages to ensure commit
        for i in range(0, len(blob), 4096):
            blob[i] = 0xFF
        time.sleep(duration_seconds)
    except MemoryError:
        logger.warning("Memory stress: could not allocate target, reduced allocation")
    finally:
        del blob  # noqa: F821 — may not exist if MemoryError


def _create_executable_artifact() -> str:
    """Create a temporary executable file for SecurityScanner to detect."""
    name = f"soak_test_{uuid.uuid4().hex[:8]}"
    path = os.path.join(tempfile.gettempdir(), name)
    with open(path, "w") as f:
        f.write("#!/bin/sh\necho soak\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    logger.info("Security artifact: created executable %s", path)
    return path


def _run_suspicious_process(duration_seconds: float = 10) -> None:
    """Run a subprocess with a suspicious name for SecurityScanner to detect."""
    name = f"xmrig_soak_test_{uuid.uuid4().hex[:8]}"
    tmp = os.path.join(tempfile.gettempdir(), name)
    with open(tmp, "w") as f:
        f.write(f"#!/bin/sh\nsleep {int(duration_seconds)}\n")
    os.chmod(tmp, os.stat(tmp).st_mode | stat.S_IEXEC)
    logger.info("Security artifact: running suspicious process %s", name)
    proc = subprocess.Popen([tmp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Let it run for the specified duration, then clean up
    try:
        proc.wait(timeout=duration_seconds + 5)
    except subprocess.TimeoutExpired:
        proc.terminate()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _emit_error_burst(count: int = 18) -> None:
    """Emit a burst of ERROR-level log messages for LogWatcher to detect."""
    burst_logger = logging.getLogger("argus.soak.error_burst")
    for i in range(count):
        burst_logger.error(
            "Soak test error burst [%d/%d]: simulated error condition id=%s",
            i + 1,
            count,
            uuid.uuid4().hex[:8],
        )


# ---------------------------------------------------------------------------
#  Soak test runner
# ---------------------------------------------------------------------------


class SoakTestRunner:
    """Drives real system activity across four domains to exercise the full pipeline."""

    def __init__(self) -> None:
        self._app_configs = parse_soak_apps()
        self._app_procs: list[subprocess.Popen[bytes]] = []
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []
        self._artifacts: list[str] = []  # temp files to clean up

        # Cooldown intervals (seconds) — centre ± jitter
        self._cpu_interval = 20 * 60      # ~20 min
        self._cpu_jitter = 5 * 60
        self._mem_interval = 30 * 60      # ~30 min
        self._mem_jitter = 5 * 60
        self._exec_interval = 45 * 60     # ~45 min
        self._exec_jitter = 10 * 60
        self._proc_interval = 60 * 60     # ~60 min
        self._proc_jitter = 10 * 60
        self._error_interval = 25 * 60    # ~25 min
        self._error_jitter = 5 * 60
        self._traffic_interval = 30       # HTTP requests every 30s

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start example apps and schedule activity loops."""
        if self._running:
            return
        self._running = True
        logger.info("Soak test runner starting (%d app configs)", len(self._app_configs))

        self._start_example_apps()

        # Give apps a few seconds to boot
        if self._app_procs:
            await asyncio.sleep(3)

        self._tasks = [
            asyncio.create_task(self._traffic_loop()),
            asyncio.create_task(self._cpu_loop()),
            asyncio.create_task(self._memory_loop()),
            asyncio.create_task(self._executable_loop()),
            asyncio.create_task(self._suspicious_proc_loop()),
            asyncio.create_task(self._error_burst_loop()),
        ]

        logger.info("Soak test runner started with %d activity loops", len(self._tasks))

    async def stop(self) -> None:
        """Stop all loops and example apps."""
        self._running = False

        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

        self._stop_example_apps()
        self._cleanup_artifacts()
        logger.info("Soak test runner stopped")

    # ------------------------------------------------------------------
    #  Example app management
    # ------------------------------------------------------------------

    def _start_example_apps(self) -> None:
        """Start configured example apps as subprocesses."""
        from argus_agent.config import get_settings

        settings = get_settings()
        agent_url = f"http://localhost:{settings.server.port}"

        for cfg in self._app_configs:
            env = {**os.environ, "ARGUS_URL": agent_url, **cfg.env}
            app_dir = Path(cfg.path)
            if not app_dir.is_absolute():
                # Resolve relative to project root (two levels up from package)
                project_root = Path(__file__).resolve().parents[4]
                app_dir = project_root / cfg.path

            if not app_dir.exists():
                logger.warning("Soak app path does not exist: %s", app_dir)
                continue

            try:
                proc = subprocess.Popen(
                    cfg.cmd.split(),
                    cwd=str(app_dir),
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid,
                )
                self._app_procs.append(proc)
                logger.info("Started soak app: %s (pid=%d, port=%d)", cfg.path, proc.pid, cfg.port)
            except Exception:
                logger.exception("Failed to start soak app: %s", cfg.path)

    def _stop_example_apps(self) -> None:
        """Terminate all example app subprocesses."""
        for proc in self._app_procs:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._app_procs.clear()

    def _cleanup_artifacts(self) -> None:
        """Remove temporary security artifacts."""
        for path in self._artifacts:
            try:
                os.unlink(path)
            except OSError:
                pass
        self._artifacts.clear()

    # ------------------------------------------------------------------
    #  Activity loops
    # ------------------------------------------------------------------

    async def _traffic_loop(self) -> None:
        """Send HTTP traffic to example apps every ~30s."""
        if not self._app_configs:
            return

        async with httpx.AsyncClient(timeout=15) as client:
            while self._running:
                for cfg in self._app_configs:
                    endpoint = _pick_endpoint()
                    url = f"http://localhost:{cfg.port}{endpoint}"
                    try:
                        await client.get(url)
                    except Exception:
                        pass  # Expected for /error, /slow etc.
                await asyncio.sleep(self._traffic_interval)

    async def _cpu_loop(self) -> None:
        """Periodic CPU stress bursts."""
        while self._running:
            wait = self._cpu_interval + random.randint(-self._cpu_jitter, self._cpu_jitter)
            await asyncio.sleep(max(wait, 60))
            if not self._running:
                break

            duration = random.uniform(15, 30)
            logger.info("CPU stress: %0.0fs burst on all cores", duration)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _cpu_stress, duration)

    async def _memory_loop(self) -> None:
        """Periodic memory stress bursts."""
        while self._running:
            wait = self._mem_interval + random.randint(-self._mem_jitter, self._mem_jitter)
            await asyncio.sleep(max(wait, 60))
            if not self._running:
                break

            fraction = random.uniform(0.7, 0.8)
            duration = 20.0
            logger.info("Memory stress: %.0f%% for %.0fs", fraction * 100, duration)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _memory_stress, duration, fraction)

    async def _executable_loop(self) -> None:
        """Periodically create executable artifacts."""
        while self._running:
            wait = self._exec_interval + random.randint(-self._exec_jitter, self._exec_jitter)
            await asyncio.sleep(max(wait, 60))
            if not self._running:
                break

            path = _create_executable_artifact()
            self._artifacts.append(path)

    async def _suspicious_proc_loop(self) -> None:
        """Periodically run a suspicious-named process."""
        while self._running:
            wait = self._proc_interval + random.randint(-self._proc_jitter, self._proc_jitter)
            await asyncio.sleep(max(wait, 60))
            if not self._running:
                break

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _run_suspicious_process, 10)

    async def _error_burst_loop(self) -> None:
        """Periodically emit ERROR log bursts."""
        while self._running:
            wait = self._error_interval + random.randint(-self._error_jitter, self._error_jitter)
            await asyncio.sleep(max(wait, 60))
            if not self._running:
                break

            logger.info("Emitting error burst")
            _emit_error_burst(count=18)
