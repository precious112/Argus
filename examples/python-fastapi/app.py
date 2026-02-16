"""Example FastAPI application instrumented with Argus SDK."""

import asyncio
import logging
import os
import random

import argus
from argus.decorators import trace
from argus.exceptions import install as install_exception_hook
from argus.logger import ArgusHandler
from argus.middleware.fastapi import ArgusMiddleware
from argus.serverless import detect_runtime

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Initialize Argus SDK with all Phase 1 features
argus.init(
    server_url=os.getenv("ARGUS_URL", "http://localhost:7600"),
    api_key=os.getenv("ARGUS_API_KEY", ""),
    service_name="example-fastapi",
    runtime_metrics=True,       # UC2: Runtime Metrics
    auto_instrument=True,       # UC3: Dependency Calls (patches httpx)
)
install_exception_hook()

# Add Argus log handler
handler = ArgusHandler()
logging.getLogger().addHandler(handler)

# Argus auto-detects serverless runtimes (Lambda, Vercel, etc.)
runtime = detect_runtime()
if runtime:
    logger_setup = logging.getLogger("example")
    logger_setup.info("Running in serverless runtime: %s", runtime)

app = FastAPI(title="Argus Example App")
app.add_middleware(ArgusMiddleware)

logger = logging.getLogger("example")

PORT = int(os.getenv("PORT", "8000"))


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "example-fastapi"}


@app.get("/users")
@trace("get_users")
async def get_users():
    """Return a list of mock users."""
    logger.info("Fetching users list")
    await asyncio.sleep(random.uniform(0.01, 0.1))
    argus.event("users_fetched", {"count": 3})
    return {
        "users": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
        ]
    }


@app.post("/error")
async def trigger_error():
    """Intentionally raise an error to test exception capture."""
    logger.error("Division by zero triggered")
    try:
        result = 1 / 0
    except ZeroDivisionError as e:
        argus.capture_exception(e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/slow")
@trace("slow_endpoint")
async def slow_endpoint():
    """Artificially slow endpoint."""
    delay = random.uniform(1, 3)
    logger.warning("Slow endpoint accessed, delay=%.2f", delay)
    await asyncio.sleep(delay)
    return {"message": "done", "delay_seconds": round(delay, 2)}


# --- Phase 1 endpoints ---


@trace("fetch_users_from_db")
async def _fetch_users_from_db():
    """Simulated DB lookup — creates a child span under the /chain trace."""
    await asyncio.sleep(random.uniform(0.02, 0.08))
    return [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
        {"id": 3, "name": "Charlie"},
    ]


@app.get("/chain")
@trace("chain_handler")
async def chain():
    """UC1+UC3: Outgoing HTTP call to self + nested trace spans.

    - Makes an httpx call to GET /users (dependency tracking + trace propagation)
    - Calls a nested @trace function (parent/child span relationship)
    """
    logger.info("Chain request: upstream + DB lookup")
    base = f"http://localhost:{PORT}"

    # Outgoing HTTP call — auto-instrumented by argus
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base}/users")
        upstream_users = resp.json()

    # Nested traced function — creates child span
    db_users = await _fetch_users_from_db()

    return {
        "upstream_users": upstream_users,
        "db_users": db_users,
    }


@app.post("/checkout")
@trace("checkout_handler")
async def checkout():
    """UC5: Error correlation with trace context + breadcrumbs.

    Adds breadcrumbs at each step, then raises an exception.
    The captured exception will include the trace_id, span_id, and breadcrumbs.
    """
    argus.add_breadcrumb("checkout", "Validating cart contents", {"items": 3})
    await asyncio.sleep(0.01)

    argus.add_breadcrumb("checkout", "Charging payment", {"amount": 99.99, "method": "card"})
    await asyncio.sleep(0.01)

    argus.add_breadcrumb("checkout", "Updating inventory")

    try:
        # Simulate a payment failure
        raise RuntimeError("Payment gateway timeout")
    except RuntimeError as e:
        logger.error("Checkout failed: payment gateway timeout")
        argus.capture_exception(e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/external")
@trace("external_call")
async def external():
    """UC3: Real external dependency tracking.

    Makes an outgoing httpx call to a public API (jsonplaceholder).
    """
    logger.info("Calling external API")
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://jsonplaceholder.typicode.com/todos/1")
        data = resp.json()

    return {"external_result": data}


@app.post("/multi-error")
@trace("multi_error_handler")
async def multi_error():
    """Generate varied exception types for error grouping analysis."""
    error_types = [
        (ValueError, "Invalid user ID format"),
        (TimeoutError, "Database connection pool exhausted"),
        (KeyError, "Missing required field: email"),
        (TypeError, "Expected string, got NoneType"),
        (RuntimeError, "Worker process crashed unexpectedly"),
    ]
    err_cls, msg = random.choice(error_types)
    argus.add_breadcrumb("multi-error", f"Selected error type: {err_cls.__name__}")
    argus.add_breadcrumb("multi-error", "Simulating failure scenario")

    try:
        raise err_cls(msg)
    except Exception as e:
        logger.error("Multi-error triggered: %s: %s", type(e).__name__, e)
        argus.capture_exception(e)
        return JSONResponse(status_code=500, content={"error": str(e), "type": type(e).__name__})


# --- Background traffic simulator ---


async def _traffic_simulator():
    """Generate background traffic to keep telemetry flowing."""
    endpoints = [
        ("GET", "/", 10),
        ("GET", "/users", 8),
        ("GET", "/chain", 4),
        ("GET", "/external", 3),
        ("GET", "/slow", 2),
        ("POST", "/checkout", 2),
        ("POST", "/multi-error", 2),
        ("POST", "/error", 1),
    ]
    weighted = []
    for method, path, weight in endpoints:
        weighted.extend([(method, path)] * weight)

    base = f"http://localhost:{PORT}"

    await asyncio.sleep(5)
    logger.info("Traffic simulator started")

    while True:
        try:
            method, path = random.choice(weighted)
            async with httpx.AsyncClient() as client:
                if method == "GET":
                    await client.get(f"{base}{path}", timeout=10.0)
                else:
                    await client.post(f"{base}{path}", timeout=10.0)
        except Exception:
            pass

        delay = random.uniform(10, 45)
        await asyncio.sleep(delay)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_traffic_simulator())


@app.on_event("shutdown")
async def shutdown():
    argus.shutdown()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
