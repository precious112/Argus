#!/usr/bin/env bash
# Argus Stress Test — Triggers alert conditions for manual testing
# Usage: bash tests/manual/stress-test.sh [cpu|memory|disk|port|logs|all]

set -euo pipefail

ARGUS_URL="${ARGUS_URL:-http://localhost:7600}"
BASE="${ARGUS_URL}/api/v1"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${CYAN}[INFO]${NC}  %s\n" "$1"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
ok()    { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
error() { printf "${RED}[ERR]${NC}   %s\n" "$1"; }

check_alerts() {
    local label="$1"
    info "Checking alerts for: ${label}"
    local alerts
    alerts=$(curl -s "${BASE}/alerts" 2>/dev/null) || { error "Failed to reach API"; return 1; }
    echo "$alerts" | jq -r '.alerts[] | "  [\(.severity)] \(.rule_name) — \(.message)"' 2>/dev/null || echo "  (no alerts or parse error)"
}

# --- CPU Stress ---
test_cpu() {
    info "CPU Stress Test — pegging all CPUs for 60s"
    info "Expected: URGENT CPU_HIGH alert within ~30s"
    echo ""

    if ! command -v stress-ng &>/dev/null; then
        error "stress-ng not installed. Run: sudo apt-get install -y stress-ng"
        return 1
    fi

    stress-ng --cpu "$(nproc)" --timeout 60 &
    local pid=$!
    info "stress-ng started (PID $pid), waiting 35s for alert..."
    sleep 35

    check_alerts "CPU Critical"

    info "Waiting for stress-ng to finish..."
    wait "$pid" 2>/dev/null || true
    ok "CPU stress test complete"
}

# --- Memory Stress ---
test_memory() {
    info "Memory Stress Test — consuming 80% RAM for 60s"
    info "Expected: URGENT MEMORY_HIGH alert within ~30s"
    echo ""

    if ! command -v stress-ng &>/dev/null; then
        error "stress-ng not installed. Run: sudo apt-get install -y stress-ng"
        return 1
    fi

    stress-ng --vm 2 --vm-bytes 80% --timeout 60 &
    local pid=$!
    info "stress-ng started (PID $pid), waiting 35s for alert..."
    sleep 35

    check_alerts "Memory Critical"

    info "Waiting for stress-ng to finish..."
    wait "$pid" 2>/dev/null || true
    ok "Memory stress test complete"
}

# --- Disk Stress ---
test_disk() {
    info "Disk Stress Test — writing 500MB temp file"
    info "Expected: URGENT DISK_HIGH alert if disk > 90% (depends on disk size)"
    echo ""

    dd if=/dev/zero of=/tmp/argus_disk_test bs=1M count=500 status=progress 2>&1 || true
    info "File written, waiting 35s for metric collection..."
    sleep 35

    check_alerts "Disk Critical"

    rm -f /tmp/argus_disk_test
    ok "Disk stress test complete (temp file removed)"
}

# --- Port Scan ---
test_port() {
    info "Port Scan Test — opening port 9999"
    info "Expected: NEW_OPEN_PORT detected in security scan (~5 min)"
    info "Note: This does NOT trigger an alert banner (not in security_event rule)"
    echo ""

    if ! command -v nc &>/dev/null; then
        error "netcat not installed. Run: sudo apt-get install -y netcat-openbsd"
        return 1
    fi

    nc -l -p 9999 &
    local pid=$!
    info "nc listening on port 9999 (PID $pid)"
    info "Waiting 330s (5.5 min) for security scan cycle..."
    sleep 330

    info "Checking security scan results:"
    curl -s "${BASE}/security" 2>/dev/null | jq '.checks' 2>/dev/null || echo "(failed)"

    kill "$pid" 2>/dev/null || true
    ok "Port scan test complete (nc killed)"
}

# --- Log Error Burst ---
test_logs() {
    info "Log Error Burst Test — writing 20 error lines to syslog"
    info "Expected: ERROR_BURST alert within ~15s (if >= 10 errors in 60s)"
    echo ""

    for i in $(seq 1 20); do
        logger -p user.err "ARGUS_TEST_ERROR: simulated error $i of 20"
    done
    info "20 error messages written to syslog, waiting 20s..."
    sleep 20

    check_alerts "Error Burst"
    ok "Log error burst test complete"
}

# --- Menu ---
usage() {
    echo ""
    echo "Argus Stress Test"
    echo ""
    echo "Usage: $0 [cpu|memory|disk|port|logs|all]"
    echo ""
    echo "Tests:"
    echo "  cpu      Peg CPU at 100% for 60s          (alert in ~30s)"
    echo "  memory   Consume 80% RAM for 60s           (alert in ~30s)"
    echo "  disk     Write 500MB temp file              (alert if disk > 90%)"
    echo "  port     Open port 9999 for 5.5 min         (security scan detection)"
    echo "  logs     Write 20 error lines to syslog     (alert in ~15s)"
    echo "  all      Run all tests sequentially"
    echo ""
    echo "Environment:"
    echo "  ARGUS_URL  API base URL (default: http://localhost:7600)"
    echo ""
}

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

case "${1:-}" in
    cpu)    test_cpu ;;
    memory) test_memory ;;
    disk)   test_disk ;;
    port)   test_port ;;
    logs)   test_logs ;;
    all)
        test_cpu
        echo ""
        echo "---"
        echo ""
        test_memory
        echo ""
        echo "---"
        echo ""
        test_disk
        echo ""
        echo "---"
        echo ""
        test_logs
        echo ""
        echo "---"
        echo ""
        warn "Skipping port test in 'all' mode (takes 5.5 min). Run separately: $0 port"
        ;;
    *)
        usage
        exit 1
        ;;
esac
