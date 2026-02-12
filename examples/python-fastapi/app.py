"""Example FastAPI application instrumented with Argus SDK."""

import asyncio
import os
import random

import argus
from argus.decorators import trace
from argus.exceptions import install as install_exception_hook
from argus.logger import ArgusHandler
from argus.middleware.fastapi import ArgusMiddleware

import logging
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Initialize Argus SDK
argus.init(
    server_url=os.getenv("ARGUS_URL", "http://localhost:7600"),
    api_key=os.getenv("ARGUS_API_KEY", ""),
    service_name="example-fastapi",
)
install_exception_hook()

# Add Argus log handler
handler = ArgusHandler()
logging.getLogger().addHandler(handler)

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


@app.on_event("shutdown")
async def shutdown():
    argus.shutdown()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
