#!/usr/bin/env bash
# Argus SDK Integration Test
# Starts the example Python app and generates traffic to verify SDK ingestion.
# Usage: bash tests/manual/test-sdk.sh

set -euo pipefail

ARGUS_URL="${ARGUS_URL:-http://localhost:7600}"
EXAMPLE_URL="${EXAMPLE_URL:-http://localhost:8000}"
BASE="${ARGUS_URL}/api/v1"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${CYAN}[INFO]${NC}  %s\n" "$1"; }
ok()    { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
error() { printf "${RED}[ERR]${NC}   %s\n" "$1"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }

echo ""
echo "========================================="
echo "  Argus SDK Integration Test"
echo "========================================="
echo ""

# --- Step 1: Start example app via compose overlay ---
info "Step 1: Starting example app via docker compose overlay..."
if docker compose -f docker-compose.yml -f tests/manual/docker-compose.test.yml up -d example-python 2>/dev/null; then
    ok "Example app container started"
else
    warn "Docker compose overlay failed. Is the example app already running?"
    warn "Trying to continue with existing app at ${EXAMPLE_URL}..."
fi

# --- Step 2: Wait for example app health ---
info "Step 2: Waiting for example app at ${EXAMPLE_URL}..."
RETRIES=15
for i in $(seq 1 $RETRIES); do
    if curl -sf "${EXAMPLE_URL}/" >/dev/null 2>&1; then
        ok "Example app is healthy"
        break
    fi
    if [[ $i -eq $RETRIES ]]; then
        error "Example app not reachable after ${RETRIES} attempts"
        error "Check: docker compose -f docker-compose.yml -f tests/manual/docker-compose.test.yml logs example-python"
        exit 1
    fi
    sleep 2
done

# --- Step 3: Generate traffic ---
info "Step 3: Generating traffic..."

echo ""
info "  5x GET /users"
for i in $(seq 1 5); do
    status=$(curl -s -o /dev/null -w '%{http_code}' "${EXAMPLE_URL}/users")
    printf "    Request %d: HTTP %s\n" "$i" "$status"
done

echo ""
info "  3x POST /error"
for i in $(seq 1 3); do
    status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${EXAMPLE_URL}/error")
    printf "    Request %d: HTTP %s\n" "$i" "$status"
done

echo ""
info "  1x GET /slow"
status=$(curl -s -o /dev/null -w '%{http_code}' "${EXAMPLE_URL}/slow")
printf "    Request 1: HTTP %s\n" "$status"

# --- Step 4: Wait for SDK flush ---
info "Step 4: Waiting 10s for SDK to flush events to Argus..."
sleep 10

# --- Step 5: Verify ingestion ---
info "Step 5: Verifying event ingestion..."

echo ""
info "  Checking /logs for SDK entries:"
LOG_COUNT=$(curl -s "${BASE}/logs?limit=50" 2>/dev/null | jq '[.entries[] | select(.source == "sdk" or .service == "example-fastapi")] | length' 2>/dev/null || echo "0")
printf "    SDK log entries found: %s\n" "$LOG_COUNT"

if [[ "$LOG_COUNT" -gt 0 ]]; then
    ok "SDK events are being ingested"
else
    warn "No SDK log entries found yet. The SDK may use a different ingestion path."
    info "  Try checking via the chat: \"What errors is my app throwing?\""
fi

echo ""
info "  Checking /alerts for SDK-related alerts:"
curl -s "${BASE}/alerts" 2>/dev/null | jq -r '.alerts[] | select(.message | test("sdk|example|exception"; "i")) | "    [\(.severity)] \(.rule_name) — \(.message)"' 2>/dev/null || echo "    (none found)"

# --- Summary ---
echo ""
echo "========================================="
echo "  SDK Integration Test Complete"
echo ""
echo "  Next steps:"
echo "    - Chat: \"What errors is my app throwing?\""
echo "    - Chat: \"Show me SDK events from example-fastapi\""
echo "    - Check: curl ${BASE}/alerts | jq"
echo "========================================="
echo ""
