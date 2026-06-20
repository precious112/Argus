#!/usr/bin/env python3
"""Payments API test runner — generates background traffic and error bursts.

Run separately from the app. Uses plain HTTP requests (no SDK import).
Chaos scenarios are triggered via the app's /_ops/simulate/* endpoints.

Usage:
    python test_runner.py

Environment:
    APP_URL  — base URL of the test app (default: http://localhost:8000)
"""

import asyncio
import json
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
    ("GET",  "/health",               8),
    ("GET",  "/v1/accounts/acct_1001", 6),
    ("GET",  "/v1/accounts/acct_1002", 4),
    ("POST", "/v1/payments/charge",    5),
    ("POST", "/v1/payments/authorize", 4),
    ("POST", "/v1/transfers/initiate", 3),
    ("GET",  "/v1/rates/convert",      3),
    ("GET",  "/v1/compliance/screen",  2),
    ("POST", "/v1/payments/refund",    2),
]

CURRENCIES = ["USD", "EUR", "GBP"]
MERCHANTS = ["mch_8291", "mch_4517", "mch_7203", "mch_1089", "mch_6345"]
ACCOUNTS = ["acct_1001", "acct_1002", "acct_1003", "acct_1004", "acct_1005"]


def _build_weighted_list() -> list[tuple[str, str]]:
    weighted: list[tuple[str, str]] = []
    for method, path, weight in ENDPOINTS:
        weighted.extend([(method, path)] * weight)
    return weighted


WEIGHTED = _build_weighted_list()


def _make_body(path: str) -> dict | None:
    """Generate a realistic JSON body for POST endpoints."""
    if path == "/v1/payments/charge":
        return {
            "amount": round(random.uniform(15.0, 500.0), 2),
            "currency": random.choice(CURRENCIES),
            "source": f"tok_visa_{random.randint(1000, 9999)}",
            "merchant_id": random.choice(MERCHANTS),
            "idempotency_key": f"idem_{random.randbytes(4).hex()}",
        }
    elif path == "/v1/payments/authorize":
        return {
            "amount": round(random.uniform(5.0, 500.0), 2),
            "currency": random.choice(CURRENCIES),
            "card_last4": str(random.randint(1000, 9999)),
            "merchant_id": random.choice(MERCHANTS),
        }
    elif path == "/v1/transfers/initiate":
        accts = random.sample(ACCOUNTS, 2)
        return {
            "from_account": accts[0],
            "to_account": accts[1],
            "amount": round(random.uniform(50.0, 5000.0), 2),
            "currency": random.choice(CURRENCIES),
        }
    elif path == "/v1/payments/refund":
        return {
            "transaction_id": f"txn_{random.randbytes(3).hex()}",
            "amount": round(random.uniform(10.0, 250.0), 2),
            "reason": random.choice(["customer_request", "duplicate", "fraudulent"]),
        }
    return None


async def traffic_loop() -> None:
    """Send weighted-random requests to the app every ~15s."""
    logger.info("Traffic loop started (target: %s)", APP_URL)
    while True:
        method, path = random.choice(WEIGHTED)
        url = f"{APP_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    resp = await client.get(url)
                else:
                    body = _make_body(path)
                    resp = await client.post(url, json=body)
                logger.info("%s %s -> %d", method, path, resp.status_code)
        except Exception as e:
            logger.warning("%s %s -> error: %s", method, path, e)

        delay = random.uniform(10, 20)
        await asyncio.sleep(delay)


async def error_burst_loop() -> None:
    """Send rapid failed authorization/refund requests every ~5 minutes."""
    logger.info("Error burst loop started")
    # Wait a bit before first burst
    await asyncio.sleep(60)

    while True:
        logger.info("=== Starting error burst (20 requests) ===")
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(20):
                try:
                    if i % 3 == 0:
                        body = _make_body("/v1/payments/refund")
                        await client.post(f"{APP_URL}/v1/payments/refund", json=body)
                    else:
                        body = _make_body("/v1/payments/authorize")
                        await client.post(f"{APP_URL}/v1/payments/authorize", json=body)
                except Exception:
                    pass
                await asyncio.sleep(0.2)
        logger.info("=== Error burst complete ===")

        # Wait ~5 minutes before next burst
        delay = random.uniform(270, 330)
        await asyncio.sleep(delay)


async def main() -> None:
    logger.info("=" * 60)
    logger.info("Payments API — Test Runner")
    logger.info("Target app: %s", APP_URL)
    logger.info("=" * 60)

    # Verify app is reachable
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{APP_URL}/health")
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
