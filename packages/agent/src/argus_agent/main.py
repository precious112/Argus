"""FastAPI entry point for Argus agent server."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from argus_agent.api.ingest import router as ingest_router
from argus_agent.api.rest import router as rest_router
from argus_agent.api.ws import router as ws_router
from argus_agent.config import get_settings
from argus_agent.storage.database import close_db, init_db
from argus_agent.storage.timeseries import close_timeseries, init_timeseries

logger = logging.getLogger("argus")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = get_settings()

    # Ensure data directory exists
    Path(settings.storage.data_dir).mkdir(parents=True, exist_ok=True)

    # Initialize databases
    await init_db(settings.storage.sqlite_path)
    init_timeseries(settings.storage.duckdb_path)

    logger.info("Argus agent server started on %s:%d", settings.server.host, settings.server.port)
    yield

    # Shutdown
    await close_db()
    close_timeseries()
    logger.info("Argus agent server stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    get_settings()

    app = FastAPI(
        title="Argus Agent",
        description="AI-Native Observability Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for web UI dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(rest_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")
    app.include_router(ingest_router, prefix="/api/v1")

    # Serve static web UI in production
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()


def main() -> None:
    """Run the Argus agent server."""
    logging.basicConfig(
        level=logging.DEBUG if get_settings().debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = get_settings()
    uvicorn.run(
        "argus_agent.main:app",
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
