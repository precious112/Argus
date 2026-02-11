#!/usr/bin/env bash
# Argus Diagnostics Collector
# Gathers system info, Docker state, logs, and API responses into a single file.
# Usage: bash tests/manual/collect-diagnostics.sh

set -euo pipefail

ARGUS_URL="${ARGUS_URL:-http://localhost:7600}"
BASE="${ARGUS_URL}/api/v1"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT="diagnostics-${TIMESTAMP}.txt"

section() {
    echo ""
    echo "================================================================"
    echo "  $1"
    echo "================================================================"
    echo ""
}

api_get() {
    local endpoint="$1"
    echo ">>> GET ${BASE}${endpoint}"
    curl -s "${BASE}${endpoint}" 2>&1 | jq . 2>/dev/null || curl -s "${BASE}${endpoint}" 2>&1 || echo "(failed to reach endpoint)"
    echo ""
}

{
    echo "Argus Diagnostics Report"
    echo "Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Target: ${ARGUS_URL}"

    # --- System Info ---
    section "System Info"
    echo "--- uname ---"
    uname -a 2>&1 || true
    echo ""
    echo "--- uptime ---"
    uptime 2>&1 || true
    echo ""
    echo "--- nproc ---"
    nproc 2>&1 || true
    echo ""
    echo "--- free -h ---"
    free -h 2>&1 || true
    echo ""
    echo "--- df -h ---"
    df -h 2>&1 || true

    # --- Docker State ---
    section "Docker State"
    echo "--- docker compose ps ---"
    docker compose ps 2>&1 || true
    echo ""
    echo "--- docker stats --no-stream ---"
    docker stats --no-stream 2>&1 || true
    echo ""
    echo "--- docker compose version ---"
    docker compose version 2>&1 || true

    # --- Agent Logs ---
    section "Agent Logs (last 200 lines)"
    docker compose logs argus --tail 200 --no-color 2>&1 || echo "(failed to get agent logs)"

    # --- Web Logs ---
    section "Web Logs (last 100 lines)"
    docker compose logs web --tail 100 --no-color 2>&1 || echo "(failed to get web logs)"

    # --- API State ---
    section "API State"

    api_get "/health"
    api_get "/status"
    api_get "/alerts"
    api_get "/budget"
    api_get "/security"
    api_get "/settings"
    api_get "/audit"
    api_get "/logs?limit=20"
    api_get "/investigations"

    # --- Environment ---
    section "Environment (.env — keys redacted)"
    if [[ -f .env ]]; then
        sed -E 's/(API_KEY=).+/\1***REDACTED***/' .env 2>/dev/null || cat .env
    else
        echo "(no .env file found in current directory)"
    fi

} > "${OUTPUT}" 2>&1

SIZE=$(du -h "${OUTPUT}" | cut -f1)
echo ""
echo "Diagnostics collected: ${OUTPUT} (${SIZE})"
echo "Paste relevant sections into your bug report."
