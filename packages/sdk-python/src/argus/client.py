"""HTTP client for pushing telemetry to Argus agent."""

from __future__ import annotations

# TODO: Phase 5 - Async HTTP transport with batching
# - Buffer events, flush every 5s or 100 events
# - Retry 3x on failure, then drop
# - Never block the application
