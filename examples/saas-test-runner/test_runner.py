#!/usr/bin/env python3
"""SaaS test runner — generates background traffic and error bursts.

Run separately from the app. Uses plain HTTP requests (no SDK import).
Chaos scenarios (down/slow/vuln) are triggered via the app's /chaos/* endpoints.

Usage:
    python test_runner.py

Environment:
    APP_URL  — base URL of the test app (default: http://localhost:8000)
"""

import asyncio
import logging
import os
import random
import sys

from dotenv import load_dotenv

load_dotenv()  # Load .env file if present

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_runner")

APP_URL = os.getenv("APP_URL", "http://localhost:8000").rstrip("/")

# Weighted endpoint list for traffic generation
ENDPOINTS = [
    ("GET", "/", 10),
    ("GET", "/users/1", 6),
    ("GET", "/users/2", 4),
    ("GET", "/chain", 3),
    ("GET", "/external", 2),
    ("GET", "/slow", 2),
    ("POST", "/checkout", 2),
    ("POST", "/multi-error", 2),
    ("POST", "/error", 1),
]


def _build_weighted_list() -> list[tuple[str, str]]:
    weighted: list[tuple[str, str]] = []
    for method, path, weight in ENDPOINTS:
        weighted.extend([(method, path)] * weight)
    return weighted


WEIGHTED = _build_weighted_list()


async def traffic_loop() -> None:
    """Send weighted-random requests to the app every ~15s."""
    logger.info("Traffic loop started (target: %s)", APP_URL)
    while True:
        method, path = random.choice(WEIGHTED)
        url = f"{APP_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if method == "GET":
                    resp = await client.get(url)
                else:
                    resp = await client.post(url)
                logger.info("%s %s -> %d", method, path, resp.status_code)
        except Exception as e:
            logger.warning("%s %s -> error: %s", method, path, e)

        delay = random.uniform(10, 20)
        await asyncio.sleep(delay)


async def error_burst_loop() -> None:
    """Send 20 rapid error requests every ~5 minutes."""
    logger.info("Error burst loop started")
    # Wait a bit before first burst
    await asyncio.sleep(60)

    while True:
        logger.info("=== Starting error burst (20 requests) ===")
        async with httpx.AsyncClient(timeout=15.0) as client:
            for i in range(20):
                try:
                    if i % 3 == 0:
                        await client.post(f"{APP_URL}/multi-error")
                    else:
                        await client.post(f"{APP_URL}/error")
                except Exception:
                    pass
                await asyncio.sleep(0.2)
        logger.info("=== Error burst complete ===")

        # Wait ~5 minutes before next burst
        delay = random.uniform(270, 330)
        await asyncio.sleep(delay)


async def main() -> None:
    logger.info("=" * 60)
    logger.info("Argus SaaS Test Runner")
    logger.info("Target app: %s", APP_URL)
    logger.info("=" * 60)

    # Verify app is reachable
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{APP_URL}/")
            logger.info("App health check: %d %s", resp.status_code, resp.json())
    except Exception as e:
        logger.error("Cannot reach app at %s: %s", APP_URL, e)
        logger.error("Start the app first: python -m uvicorn app:app --host 0.0.0.0 --port 8000")
        sys.exit(1)

    # Run traffic and error burst loops concurrently
    logger.info("Starting traffic generation...")
    await asyncio.gather(
        traffic_loop(),
        error_burst_loop(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Test runner stopped")
