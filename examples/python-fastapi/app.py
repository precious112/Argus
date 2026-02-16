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


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "example-fastapi"}


@app.get("/users")
@trace("get_users")
async def get_users():
    """Return a list of mock users."""
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
    import httpx

    port = os.getenv("PORT", "8000")
    base = f"http://localhost:{port}"

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
        argus.capture_exception(e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/external")
@trace("external_call")
async def external():
    """UC3: Real external dependency tracking.

    Makes an outgoing httpx call to a public API (jsonplaceholder).
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get("https://jsonplaceholder.typicode.com/todos/1")
        data = resp.json()

    return {"external_result": data}


@app.on_event("shutdown")
async def shutdown():
    argus.shutdown()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
