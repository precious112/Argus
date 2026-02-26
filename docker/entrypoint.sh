#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Argus unified entrypoint — runs agent + web in one container
# ============================================================

# --- Optional runtime URL rewrite --------------------------
# If ARGUS_PUBLIC_URL is set, replace the baked-in localhost
# URLs in the Next.js JS bundles so the UI can reach the
# agent on a remote host, and auto-configure CORS.
if [ -n "${ARGUS_PUBLIC_URL:-}" ]; then
    ARGUS_PUBLIC_URL="${ARGUS_PUBLIC_URL%/}"  # strip trailing slash
    WS_URL=$(echo "$ARGUS_PUBLIC_URL" | sed 's|^http|ws|')

    echo "[argus] Rewriting Next.js bundles → ${ARGUS_PUBLIC_URL}"
    find /app/web/.next -name '*.js' -exec sed -i \
        -e "s|http://localhost:7600|${ARGUS_PUBLIC_URL}|g" \
        -e "s|ws://localhost:7600|${WS_URL}|g" \
        {} +

    # Derive the web origin (same host, port 3000) for CORS
    WEB_ORIGIN=$(echo "$ARGUS_PUBLIC_URL" | sed 's|:[0-9]*$||'):3000
    if [ -z "${ARGUS_CORS_ORIGINS:-}" ]; then
        export ARGUS_CORS_ORIGINS="http://localhost:3000,${WEB_ORIGIN}"
        echo "[argus] Auto-set CORS origins → ${ARGUS_CORS_ORIGINS}"
    fi
fi

# --- Graceful shutdown -------------------------------------
PIDS=()

cleanup() {
    echo "[argus] Shutting down..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait
    exit 0
}

trap cleanup SIGTERM SIGINT

# --- Start agent server (uvicorn) --------------------------
echo "[argus] Starting agent server on :7600"
python -m uvicorn argus_agent.main:app \
    --host 0.0.0.0 --port 7600 &
PIDS+=($!)

# --- Start Next.js web UI ----------------------------------
echo "[argus] Starting web UI on :3000"
cd /app/web && node server.js &
PIDS+=($!)
cd /app

# --- Wait for either process to exit -----------------------
# If one crashes, stop the other so Docker can restart the
# container as a unit.
wait -n
EXIT_CODE=$?

echo "[argus] Process exited (code $EXIT_CODE), stopping remaining..."
cleanup
