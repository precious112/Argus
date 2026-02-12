# Argus Manual Testing Guide

Comprehensive manual testing workflow for Argus on a Ubuntu 22.04 VM.

---

## VM Prerequisites

| Requirement | Minimum |
|-------------|---------|
| OS | Ubuntu 22.04 LTS |
| RAM | 4 GB |
| vCPUs | 2 |
| Disk | 20 GB |
| Docker Engine | 24+ |
| Docker Compose | v2 (plugin) |

**Install dependencies:**

```bash
sudo apt-get update
sudo apt-get install -y git curl jq stress-ng netcat-openbsd
```

**Firewall:** Open ports **3000** (web UI) and **7600** (API/WebSocket).

```bash
sudo ufw allow 3000/tcp
sudo ufw allow 7600/tcp
```

---

## Deployment

```bash
# Clone and checkout
git clone <your-repo-url> ~/argus && cd ~/argus
git checkout test/argus-v1

# Configure environment
cp .env.example .env
nano .env  # Edit with your Gemini config (see below)

# Build and start
docker compose build --parallel
docker compose up -d

# Wait for services to initialize
sleep 15

# Verify
curl http://localhost:7600/api/v1/health
```

### Gemini `.env` Configuration

```env
ARGUS_LLM_PROVIDER=gemini
ARGUS_LLM_API_KEY=<your-gemini-api-key>
ARGUS_LLM_MODEL=gemini-2.0-flash
ARGUS_HOST=<vm-public-ip>
```

> **IMPORTANT:** `ARGUS_HOST` must be set to the VM's public IP address if you're accessing
> the web UI from your local browser. This value is used for CORS origins and WebSocket URLs
> baked into the web UI at build time. If you only access from the VM itself, `localhost` works.

---

## Test Phases

Run these in order. Each phase validates a different subsystem.

### Phase A: Infrastructure (no AI needed)

| Step | Test | Command / Action | Expected |
|------|------|------------------|----------|
| A1 | Docker build | `docker compose build --parallel` | Both images build without errors |
| A2 | Services start | `docker compose up -d && sleep 15` | `curl http://localhost:7600/api/v1/health` returns `{"status":"healthy"}` |
| A3 | Web UI loads | Browser: `http://<ip>:3000` | Chat UI renders with dark theme |
| A4 | WebSocket connects | Check StatusBar in web UI | Green "Connected" dot; CPU/Mem/Disk populate within 15s |
| A5 | API smoke test | `bash tests/manual/smoke-test.sh` | All endpoints return PASS |

### Phase B: Monitoring & Collection

| Step | Test | Wait | Expected |
|------|------|------|----------|
| B1 | Live metrics | 15s (metrics interval) | StatusBar shows real CPU%, Memory (GB), Disk% |
| B2 | Process list | 30s (process interval) | `curl http://localhost:7600/api/v1/status \| jq '.system.top_processes'` is populated |
| B3 | Log entries | ~5s (log poll = 2s) | `curl http://localhost:7600/api/v1/logs \| jq '.entries \| length'` > 0 (if syslog has entries) |
| B4 | Security scan | 5 min (scan interval) | `curl http://localhost:7600/api/v1/security \| jq '.checks'` has results for all 7 check types |

### Phase C: AI Chat (requires Gemini key)

| Step | Prompt | Expected Tool Call | Expected Behavior |
|------|--------|--------------------|-------------------|
| C1 | "What's the current system status?" | `get_system_metrics` | Streaming response with real CPU/mem/disk data |
| C2 | "Show me top processes by CPU" | `get_process_list` | ToolResultCard with `process_table` display |
| C3 | "Search logs for errors" | `search_logs` | ToolResultCard with `log_viewer` display |
| C4 | "Run a security scan" | `run_security_scan` | Security findings in natural language |
| C5 | Check budget | `curl http://localhost:7600/api/v1/budget \| jq` | `hourly_used > 0`, `total_requests > 0` |

### Phase D: Alerting & Auto-Investigation

**Timing:** SystemMetricsCollector runs every 15s. CPU >= 95% triggers `URGENT` via EventClassifier. Matches `cpu_critical` alert rule (auto_investigate=True). Alert cooldown = 300s.

| Step | Action | Wait | Expected |
|------|--------|------|----------|
| D1 | Install stress-ng | `sudo apt-get install -y stress-ng` | Installed |
| D2 | Spike CPU | `stress-ng --cpu 4 --timeout 120` | CPU pegged at ~100% |
| D3 | Watch AlertBanner | ~30s (2x 15s metric cycles) | Red URGENT banner: "CPU Critical" |
| D4 | Query alerts | `curl http://localhost:7600/api/v1/alerts \| jq` | Alert with `severity: "URGENT"`, `rule_name: "CPU Critical"` |
| D5 | Check investigations | `curl http://localhost:7600/api/v1/investigations \| jq` | Auto-investigation entry (budget permitting) |
| D6 | Resolve alert | `curl -X POST http://localhost:7600/api/v1/alerts/<id>/resolve` | Returns 200 |

### Phase E: Security Events

**Note:** `NEW_OPEN_PORT` publishes as NOTABLE severity but the `security_event` alert rule does NOT include it in its event_types list. So no AlertBanner for this — verify via `GET /security` instead.

| Step | Action | Wait | Expected |
|------|--------|------|----------|
| E1 | Open a port | `nc -l -p 9999 &` | Port 9999 listening |
| E2 | Wait for scan | 5 min (security scan interval) | SecurityScanner detects new port |
| E3 | Verify | `curl http://localhost:7600/api/v1/security \| jq '.checks'` | Port 9999 in open_ports results |
| E4 | Close port | `kill %1` then wait 5 min | Port gone from next scan |
| E5 | Ask agent | Chat: "Any security concerns?" | Agent references port finding or security scan results |

### Phase F: SDK Integration (Python Example App)

**Known limitation:** The `argus-python` SDK package is not published to PyPI. Options:
1. Use `docker-compose.test.yml` overlay which builds the example with SDK bundled (recommended)
2. Install SDK locally: `cd packages/sdk-python && pip install -e .`
3. Skip Phase F if SDK install fails

| Step | Action | Expected |
|------|--------|----------|
| F1 | Start example app | `docker compose -f docker-compose.yml -f tests/manual/docker-compose.test.yml up -d` | example-python at :8000 |
| F2 | Generate traffic | `for i in $(seq 1 5); do curl http://localhost:8000/users; done` | 200 responses, SDK events sent |
| F3 | Trigger errors | `for i in $(seq 1 3); do curl -X POST http://localhost:8000/error; done` | Exception captured |
| F4 | Slow request | `curl http://localhost:8000/slow` | Traced, 1-3s delay |
| F5 | Ask agent | Chat: "What errors is my app throwing?" | Agent uses `query_sdk_events` |
| F6 | Check alerts | `curl http://localhost:7600/api/v1/alerts \| jq` | Check for SDK exception alerts |

Or use the helper script: `bash tests/manual/test-sdk.sh`

### Phase G: Action Approval

**How approval works:** The `kill` command is in the sandbox allowlist with `ToolRisk.HIGH`. This triggers ActionEngine to broadcast `ACTION_REQUEST` via WebSocket. The UI shows an ActionApproval component. User clicks Approve/Reject. `ACTION_RESPONSE` sent back. Engine executes or logs rejection.

| Step | Action | Expected |
|------|--------|----------|
| G1 | Start target process | `sleep 9999 &` | Background process running |
| G2 | Ask agent | Chat: "Kill the sleep process" | ActionApproval card with risk badge |
| G3 | Click Reject | Audit log records rejection |
| G4 | Ask again, click Approve | Process killed, audit records success |
| G5 | Check audit | `curl http://localhost:7600/api/v1/audit \| jq` | Both entries (rejected + approved) |

### Phase H: History & Settings

| Step | Action | Expected |
|------|--------|----------|
| H1 | Browse `/history` | Alerts tab lists Phase D alerts; Investigations tab shows entries |
| H2 | Browse `/settings` | Shows provider: gemini, model: gemini-2.0-flash, NO API keys exposed |
| H3 | Check budget | `curl http://localhost:7600/api/v1/budget \| jq` | Cumulative token usage from all AI interactions |

---

## Helper Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `smoke-test.sh` | Automated API endpoint verification | `bash tests/manual/smoke-test.sh` |
| `stress-test.sh` | Trigger alert conditions | `bash tests/manual/stress-test.sh [cpu\|memory\|disk\|port\|logs\|all]` |
| `test-sdk.sh` | SDK integration test | `bash tests/manual/test-sdk.sh` |
| `collect-diagnostics.sh` | Gather logs/state for bug reports | `bash tests/manual/collect-diagnostics.sh` |

---

## Bug Reporting Flow

```
1. Hit a bug at test step X
2. Run: bash tests/manual/collect-diagnostics.sh
3. Open: tests/manual/BUG_REPORT_TEMPLATE.md
4. Fill in: phase/step, expected vs actual, paste relevant log sections
5. Paste the filled report into our conversation
6. I fix the issue, you re-test that specific step
```

---

## Rebuilding After Fixes

```bash
cd ~/argus
git pull
docker compose build --parallel
docker compose down && docker compose up -d
sleep 15
curl http://localhost:7600/api/v1/health
```

To reset all data (alerts, investigations, logs):

```bash
docker compose down -v   # removes volumes
docker compose up -d
```
