"""SaaS test runner — FastAPI app with Argus SDK + webhook handler.

Runs on the tenant's VM. Provides:
- SDK telemetry (traces, errors, metrics) sent to Argus SaaS
- Webhook handler for remote tool execution from Argus SaaS
- Test endpoints that generate various types of telemetry
"""

import asyncio
import logging
import os
import random

import argus
from argus.decorators import trace
from argus.exceptions import install as install_exception_hook
from argus.logger import ArgusHandler
from argus.middleware.fastapi import ArgusMiddleware
from argus.webhook import ArgusWebhookHandler

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Initialize Argus SDK
argus.init(
    server_url=os.getenv("ARGUS_URL", "http://localhost:80"),
    api_key=os.getenv("ARGUS_API_KEY", ""),
    service_name=os.getenv("SERVICE_NAME", "saas-demo-app"),
    runtime_metrics=True,
    auto_instrument=True,
)
install_exception_hook()

# Add Argus log handler
handler = ArgusHandler()
logging.getLogger().addHandler(handler)

app = FastAPI(title="Argus SaaS Test App")
app.add_middleware(ArgusMiddleware)

# Mount webhook handler for remote tool execution
webhook_secret = os.getenv("ARGUS_WEBHOOK_SECRET", "")
if webhook_secret:
    wh_handler = ArgusWebhookHandler(webhook_secret=webhook_secret)
    app.include_router(wh_handler.fastapi_router())

logger = logging.getLogger("saas-demo")

PORT = int(os.getenv("PORT", "8000"))


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": os.getenv("SERVICE_NAME", "saas-demo-app")}


@app.get("/users/{user_id}")
@trace("get_user")
async def get_user(user_id: int):
    """Return a mock user."""
    logger.info("Fetching user %d", user_id)
    await asyncio.sleep(random.uniform(0.01, 0.1))
    argus.event("user_fetched", {"user_id": user_id})
    return {"id": user_id, "name": f"User-{user_id}", "email": f"user{user_id}@example.com"}


@app.post("/error")
async def trigger_error():
    """Intentionally raise an error to test exception capture."""
    logger.error("Division by zero triggered")
    try:
        _ = 1 / 0
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


@app.get("/chain")
@trace("chain_handler")
async def chain():
    """Outgoing HTTP call + nested trace spans."""
    logger.info("Chain request: upstream + lookup")
    base = f"http://localhost:{PORT}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base}/users/1")
        upstream = resp.json()

    await asyncio.sleep(random.uniform(0.02, 0.08))
    return {"upstream": upstream, "internal": "ok"}


@app.post("/checkout")
@trace("checkout_handler")
async def checkout():
    """Error correlation with trace context + breadcrumbs."""
    argus.add_breadcrumb("checkout", "Validating cart contents", {"items": 3})
    await asyncio.sleep(0.01)

    argus.add_breadcrumb("checkout", "Charging payment", {"amount": 99.99, "method": "card"})
    await asyncio.sleep(0.01)

    argus.add_breadcrumb("checkout", "Updating inventory")

    try:
        raise RuntimeError("Payment gateway timeout")
    except RuntimeError as e:
        logger.error("Checkout failed: payment gateway timeout")
        argus.capture_exception(e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/external")
@trace("external_call")
async def external():
    """External dependency tracking."""
    logger.info("Calling external API")
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://jsonplaceholder.typicode.com/todos/1")
        data = resp.json()
    return {"external_result": data}


@app.post("/multi-error")
@trace("multi_error_handler")
async def multi_error():
    """Generate varied exception types for error grouping."""
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


@app.on_event("shutdown")
async def shutdown():
    argus.shutdown()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
