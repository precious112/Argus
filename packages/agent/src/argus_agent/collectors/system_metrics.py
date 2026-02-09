"""System metrics collector using psutil."""

from __future__ import annotations

# TODO: Phase 2 - Collect CPU, memory, disk, network metrics every 15s
# - Store in DuckDB time-series
# - Emit events to event bus
# - Host-aware: prefix paths with ARGUS_HOST_ROOT
