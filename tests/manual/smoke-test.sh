#!/usr/bin/env bash
# Argus API Smoke Test
# Verifies all REST endpoints return expected responses.
# Usage: bash tests/manual/smoke-test.sh
#   env ARGUS_URL=http://1.2.3.4:7600 bash tests/manual/smoke-test.sh
#   env TEST_AI=true bash tests/manual/smoke-test.sh  (also tests /ask)

set -euo pipefail

ARGUS_URL="${ARGUS_URL:-http://localhost:7600}"
BASE="${ARGUS_URL}/api/v1"
TEST_AI="${TEST_AI:-false}"

PASS=0
FAIL=0
ERRORS=()

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { PASS=$((PASS + 1)); printf "${GREEN}  PASS${NC} %s\n" "$1"; }
fail() { FAIL=$((FAIL + 1)); ERRORS+=("$1: $2"); printf "${RED}  FAIL${NC} %s — %s\n" "$1" "$2"; }

# test_endpoint NAME METHOD URL EXPECTED_STATUS [JQ_CHECK]
test_endpoint() {
    local name="$1" method="$2" url="$3" expected="$4" jq_check="${5:-}"
    local body="${6:-}"

    local curl_args=(-s -o /tmp/smoke_body -w '%{http_code}' -X "$method")
    if [[ -n "$body" ]]; then
        curl_args+=(-H 'Content-Type: application/json' -d "$body")
    fi

    local status
    status=$(curl "${curl_args[@]}" "$url" 2>/dev/null) || {
        fail "$name" "curl failed (is Argus running at ${ARGUS_URL}?)"
        return
    }

    if [[ "$status" != "$expected" ]]; then
        fail "$name" "HTTP $status (expected $expected)"
        return
    fi

    if [[ -n "$jq_check" ]]; then
        local result
        result=$(jq -r "$jq_check" /tmp/smoke_body 2>/dev/null) || {
            fail "$name" "jq check failed: $jq_check"
            return
        }
        if [[ "$result" == "null" || -z "$result" ]]; then
            fail "$name" "jq check returned null/empty: $jq_check"
            return
        fi
    fi

    pass "$name"
}

echo ""
echo "========================================="
echo "  Argus API Smoke Test"
echo "  Target: ${ARGUS_URL}"
echo "========================================="
echo ""

# --- Core endpoints ---

echo "--- Core ---"
test_endpoint "GET /health" \
    GET "${BASE}/health" 200 '.status'

test_endpoint "GET /status" \
    GET "${BASE}/status" 200 '.collectors'

# --- Alerts ---

echo "--- Alerts ---"
test_endpoint "GET /alerts" \
    GET "${BASE}/alerts" 200 '.alerts | type'

test_endpoint "GET /alerts?severity=URGENT" \
    GET "${BASE}/alerts?severity=URGENT" 200

# --- AI/Investigations ---

echo "--- AI ---"
test_endpoint "GET /investigations" \
    GET "${BASE}/investigations" 200 '.investigations | type'

test_endpoint "GET /budget" \
    GET "${BASE}/budget" 200 '.hourly_limit'

# --- Settings ---

echo "--- Settings ---"
test_endpoint "GET /settings" \
    GET "${BASE}/settings" 200 '.llm.provider'

# --- Security ---

echo "--- Security ---"
test_endpoint "GET /security" \
    GET "${BASE}/security" 200

# --- Logs ---

echo "--- Logs ---"
test_endpoint "GET /logs" \
    GET "${BASE}/logs" 200 '.entries | type'

test_endpoint "GET /logs?severity=ERROR" \
    GET "${BASE}/logs?severity=ERROR" 200

# --- Audit ---

echo "--- Audit ---"
test_endpoint "GET /audit" \
    GET "${BASE}/audit" 200 '.entries | type'

# --- Ingest ---

echo "--- Ingest ---"
SAMPLE_BATCH='{"events":[{"type":"log","service":"smoke-test","data":{"message":"test event 1","level":"info"}},{"type":"metric","service":"smoke-test","data":{"name":"test.latency","value":42}}]}'

test_endpoint "POST /ingest (2 events)" \
    POST "${BASE}/ingest" 200 '.accepted' "$SAMPLE_BATCH"

# --- AI Chat (conditional) ---

if [[ "$TEST_AI" == "true" ]]; then
    echo "--- AI Chat ---"
    ASK_BODY='{"question":"What is the current CPU usage? Reply in one sentence."}'
    test_endpoint "POST /ask" \
        POST "${BASE}/ask" 200 '.answer' "$ASK_BODY"
else
    printf "${YELLOW}  SKIP${NC} POST /ask (set TEST_AI=true to enable)\n"
fi

# --- Summary ---

echo ""
echo "========================================="
TOTAL=$((PASS + FAIL))
printf "  Results: ${GREEN}%d passed${NC}, ${RED}%d failed${NC} / %d total\n" "$PASS" "$FAIL" "$TOTAL"

if [[ ${#ERRORS[@]} -gt 0 ]]; then
    echo ""
    echo "  Failures:"
    for err in "${ERRORS[@]}"; do
        printf "    ${RED}*${NC} %s\n" "$err"
    done
fi

echo "========================================="
echo ""

[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
