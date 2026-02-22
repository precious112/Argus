"""Argus Test Runner — drives real traffic to instrumented example apps
and triggers system-level events for host collectors.

Configured via environment variables:
  TARGET_APP         — "fastapi", "express", or "both" (default "both")
  TARGET_APPS        — JSON list of {"name","url"} objects (overrides TARGET_APP)
  SCENARIO_INTERVAL  — seconds between full scenario cycles (default 300)
  ENABLE_SYSTEM_STRESS — run CPU/memory/process scenarios (default true)

CLI usage:
  python runner.py [fastapi|express|both]
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
import sys
import tempfile
import time
from dataclasses import dataclass

import httpx
import psutil

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("test-runner")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class AppTarget:
    name: str
    url: str


PRESETS: dict[str, list[dict[str, str]]] = {
    "fastapi": [{"name": "fastapi", "url": "http://example-fastapi:8000"}],
    "express": [{"name": "express", "url": "http://example-express:8001"}],
    "both": [
        {"name": "fastapi", "url": "http://example-fastapi:8000"},
        {"name": "express", "url": "http://example-express:8001"},
    ],
}


def load_targets(cli_app: str | None = None) -> list[AppTarget]:
    # Explicit TARGET_APPS JSON takes highest precedence
    raw = os.environ.get("TARGET_APPS")
    if raw:
        return [AppTarget(**t) for t in json.loads(raw)]

    # CLI arg > TARGET_APP env var > default "both"
    app = cli_app or os.environ.get("TARGET_APP", "both")
    app = app.lower().strip()
    if app not in PRESETS:
        logger.error("Unknown app %r — expected one of: %s", app, ", ".join(PRESETS))
        sys.exit(1)

    return [AppTarget(**t) for t in PRESETS[app]]


SCENARIO_INTERVAL = int(os.environ.get("SCENARIO_INTERVAL", "300"))
ENABLE_SYSTEM_STRESS = os.environ.get("ENABLE_SYSTEM_STRESS", "true").lower() in (
    "true",
    "1",
    "yes",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    timeout: float = 15.0,
) -> httpx.Response | None:
    try:
        resp = await client.request(method, url, timeout=timeout)
        return resp
    except Exception as exc:
        logger.debug("Request %s %s failed: %s", method, url, exc)
        return None


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

class Scenario:
    name: str = "base"

    async def run(self, targets: list[AppTarget]) -> None:
        raise NotImplementedError


class BaselineTraffic(Scenario):
    """Steady low-rate requests across all endpoints for ~5 minutes."""

    name = "baseline_traffic"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Baseline Traffic ===")
        endpoints = [
            ("GET", "/", 10),
            ("GET", "/users", 8),
            ("GET", "/chain", 3),
            ("GET", "/external", 2),
            ("GET", "/slow", 1),
            ("POST", "/checkout", 1),
            ("POST", "/error", 1),
        ]
        weighted: list[tuple[str, str]] = []
        for method, path, weight in endpoints:
            weighted.extend([(method, path)] * weight)

        duration = 300  # 5 minutes
        start = time.monotonic()
        async with httpx.AsyncClient() as client:
            while time.monotonic() - start < duration:
                target = random.choice(targets)
                method, path = random.choice(weighted)
                url = f"{target.url}{path}"
                resp = await _request(client, method, url)
                if resp:
                    logger.info(
                        "[baseline] %s %s -> %d", method, url, resp.status_code
                    )
                delay = random.uniform(15, 30)
                await asyncio.sleep(delay)
        logger.info("=== Baseline Traffic complete ===")


class ErrorBurst(Scenario):
    """Rapid-fire errors for 2-3 minutes."""

    name = "error_burst"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Error Burst ===")
        duration = random.uniform(150, 210)
        start = time.monotonic()
        async with httpx.AsyncClient() as client:
            while time.monotonic() - start < duration:
                target = random.choice(targets)
                endpoint = random.choice(["/error", "/multi-error"])
                url = f"{target.url}{endpoint}"
                resp = await _request(client, "POST", url)
                if resp:
                    logger.info(
                        "[error-burst] POST %s -> %d", url, resp.status_code
                    )
                delay = random.uniform(0.3, 1.0)
                await asyncio.sleep(delay)
        logger.info("=== Error Burst complete ===")


class LatencySpike(Scenario):
    """Hit /slow repeatedly for 5 minutes."""

    name = "latency_spike"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Latency Spike ===")
        duration = 300
        start = time.monotonic()
        async with httpx.AsyncClient() as client:
            while time.monotonic() - start < duration:
                target = random.choice(targets)
                url = f"{target.url}/slow"
                resp = await _request(client, "GET", url, timeout=30.0)
                if resp:
                    logger.info(
                        "[latency] GET %s -> %d", url, resp.status_code
                    )
                delay = random.uniform(5, 15)
                await asyncio.sleep(delay)
        logger.info("=== Latency Spike complete ===")


class DependencyChain(Scenario):
    """Hit /chain and /external to generate trace graphs."""

    name = "dependency_chain"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Dependency Chain ===")
        async with httpx.AsyncClient() as client:
            for _ in range(20):
                target = random.choice(targets)
                endpoint = random.choice(["/chain", "/external"])
                url = f"{target.url}{endpoint}"
                resp = await _request(client, "GET", url, timeout=30.0)
                if resp:
                    logger.info(
                        "[chain] GET %s -> %d", url, resp.status_code
                    )
                await asyncio.sleep(random.uniform(3, 10))
        logger.info("=== Dependency Chain complete ===")


class CheckoutFailures(Scenario):
    """POST /checkout to generate breadcrumbed exceptions."""

    name = "checkout_failures"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Checkout Failures ===")
        async with httpx.AsyncClient() as client:
            for _ in range(15):
                target = random.choice(targets)
                url = f"{target.url}/checkout"
                resp = await _request(client, "POST", url)
                if resp:
                    logger.info(
                        "[checkout] POST %s -> %d", url, resp.status_code
                    )
                await asyncio.sleep(random.uniform(2, 8))
        logger.info("=== Checkout Failures complete ===")


class TrafficBurst(Scenario):
    """Simulate a sudden traffic spike — tests traffic burst detection."""

    name = "traffic_burst"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Traffic Burst ===")
        target = random.choice(targets)
        endpoint = random.choice(["/", "/users"])
        url = f"{target.url}{endpoint}"
        count = random.randint(80, 120)
        logger.info("Sending %d rapid requests to %s", count, url)
        async with httpx.AsyncClient() as client:
            for i in range(count):
                resp = await _request(client, "GET", url)
                if resp:
                    logger.info(
                        "[traffic-burst] GET %s -> %d (%d/%d)",
                        url, resp.status_code, i + 1, count,
                    )
                delay = random.uniform(0.3, 1.0)
                await asyncio.sleep(delay)
        logger.info("=== Traffic Burst complete ===")


class MixedRealistic(Scenario):
    """Weighted random requests mimicking real user behavior."""

    name = "mixed_realistic"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Mixed Realistic ===")
        endpoints = [
            ("GET", "/", 15),
            ("GET", "/users", 10),
            ("POST", "/error", 3),
            ("POST", "/multi-error", 3),
            ("GET", "/slow", 2),
            ("GET", "/chain", 4),
            ("GET", "/external", 3),
            ("POST", "/checkout", 3),
        ]
        weighted: list[tuple[str, str]] = []
        for method, path, weight in endpoints:
            weighted.extend([(method, path)] * weight)

        duration = 300
        start = time.monotonic()
        async with httpx.AsyncClient() as client:
            while time.monotonic() - start < duration:
                target = random.choice(targets)
                method, path = random.choice(weighted)
                url = f"{target.url}{path}"
                resp = await _request(client, method, url)
                if resp:
                    logger.info(
                        "[mixed] %s %s -> %d", method, url, resp.status_code
                    )
                delay = random.uniform(5, 20)
                await asyncio.sleep(delay)
        logger.info("=== Mixed Realistic complete ===")


# ---------------------------------------------------------------------------
# System stress scenarios
# ---------------------------------------------------------------------------

def _cpu_burn(duration_secs: int) -> None:
    """Burn a single core for *duration_secs* seconds (runs in a subprocess)."""
    end = time.monotonic() + duration_secs
    while time.monotonic() < end:
        _ = sum(i * i for i in range(10_000))


class CpuStress(Scenario):
    """Burn all cores for 15-30s."""

    name = "cpu_stress"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: CPU Stress ===")
        duration = random.randint(15, 30)
        cores = multiprocessing.cpu_count()
        logger.info("Burning %d cores for %ds", cores, duration)

        loop = asyncio.get_running_loop()
        procs: list[multiprocessing.Process] = []
        for _ in range(cores):
            p = multiprocessing.Process(target=_cpu_burn, args=(duration,))
            p.start()
            procs.append(p)

        # Wait for them all to finish without blocking the event loop
        await loop.run_in_executor(None, lambda: [p.join() for p in procs])
        logger.info("=== CPU Stress complete ===")


class MemoryPressure(Scenario):
    """Allocate ~50% of available RAM for 20s."""

    name = "memory_pressure"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Memory Pressure ===")
        mem = psutil.virtual_memory()
        alloc_bytes = int(mem.available * 0.85)
        alloc_mb = alloc_bytes // (1024 * 1024)
        logger.info("Allocating ~%d MB for 20s", alloc_mb)

        # Allocate in the event loop thread — it's fast, just a big bytearray
        blob = bytearray(alloc_bytes)
        # Touch every page to ensure physical allocation
        for i in range(0, len(blob), 4096):
            blob[i] = 0xFF
        await asyncio.sleep(20)
        del blob
        logger.info("=== Memory Pressure complete ===")


class SuspiciousActivity(Scenario):
    """Create a suspicious process name and a temp executable artifact."""

    name = "suspicious_activity"

    async def run(self, targets: list[AppTarget]) -> None:
        logger.info("=== Scenario: Suspicious Activity ===")

        # 1. Run a process with a suspicious name (like a crypto miner)
        fake_name = "xmrig"
        logger.info("Spawning suspicious process: %s", fake_name)
        try:
            # Create a temp script with suspicious name
            tmp_dir = tempfile.mkdtemp()
            script_path = os.path.join(tmp_dir, fake_name)
            with open(script_path, "w") as f:
                f.write("#!/bin/sh\nsleep 30\n")
            os.chmod(script_path, stat.S_IRWXU)
            proc = subprocess.Popen(
                [script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Suspicious process PID: %d", proc.pid)
            await asyncio.sleep(30)
            proc.terminate()
            proc.wait(timeout=5)
        except Exception as exc:
            logger.warning("Suspicious process scenario error: %s", exc)

        # 2. Create a temp executable artifact for SecurityScanner detection
        logger.info("Creating temp executable artifact")
        try:
            fd, exe_path = tempfile.mkstemp(prefix="argus_test_exe_", suffix=".bin")
            os.write(fd, b"#!/bin/sh\necho test\n")
            os.close(fd)
            os.chmod(exe_path, stat.S_IRWXU)
            logger.info("Temp executable at: %s", exe_path)
            await asyncio.sleep(15)
            os.unlink(exe_path)
            logger.info("Temp executable removed")
        except Exception as exc:
            logger.warning("Executable artifact scenario error: %s", exc)

        logger.info("=== Suspicious Activity complete ===")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class ScenarioRunner:
    def __init__(self, targets: list[AppTarget]) -> None:
        self.targets = targets
        self.traffic_scenarios: list[Scenario] = [
            BaselineTraffic(),
            ErrorBurst(),
            LatencySpike(),
            DependencyChain(),
            CheckoutFailures(),
            TrafficBurst(),
            MixedRealistic(),
        ]
        self.system_scenarios: list[Scenario] = [
            CpuStress(),
            MemoryPressure(),
            SuspiciousActivity(),
        ]

    async def wait_for_targets(self, timeout: float = 120) -> None:
        """Block until all target apps respond to GET /."""
        logger.info("Waiting for target apps to be ready...")
        start = time.monotonic()
        async with httpx.AsyncClient() as client:
            for target in self.targets:
                while True:
                    elapsed = time.monotonic() - start
                    if elapsed > timeout:
                        logger.warning(
                            "Timeout waiting for %s — proceeding anyway", target.name
                        )
                        break
                    try:
                        resp = await client.get(f"{target.url}/", timeout=5.0)
                        if resp.status_code < 500:
                            logger.info("  %s is ready (%d)", target.name, resp.status_code)
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(2)
        logger.info("All targets checked — starting scenarios")

    async def run_forever(self) -> None:
        await self.wait_for_targets()

        cycle = 0
        while True:
            cycle += 1
            logger.info("====== Scenario cycle %d ======", cycle)

            for scenario in self.traffic_scenarios:
                logger.info("Starting scenario: %s", scenario.name)
                try:
                    await scenario.run(self.targets)
                except Exception:
                    logger.exception("Scenario %s failed", scenario.name)
                # Brief pause between scenarios
                await asyncio.sleep(10)

            if ENABLE_SYSTEM_STRESS:
                for scenario in self.system_scenarios:
                    logger.info("Starting system scenario: %s", scenario.name)
                    try:
                        await scenario.run(self.targets)
                    except Exception:
                        logger.exception("System scenario %s failed", scenario.name)
                    await asyncio.sleep(10)

            logger.info(
                "====== Cycle %d complete — sleeping %ds ======",
                cycle,
                SCENARIO_INTERVAL,
            )
            await asyncio.sleep(SCENARIO_INTERVAL)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    cli_app = sys.argv[1] if len(sys.argv) > 1 else None
    targets = load_targets(cli_app)
    logger.info("Test runner starting with targets: %s", [t.name for t in targets])
    logger.info(
        "Config: interval=%ds, system_stress=%s",
        SCENARIO_INTERVAL,
        ENABLE_SYSTEM_STRESS,
    )

    runner = ScenarioRunner(targets)

    loop = asyncio.new_event_loop()

    def _shutdown(sig: int, _frame: object) -> None:
        logger.info("Received signal %d — shutting down", sig)
        loop.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(runner.run_forever())
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
