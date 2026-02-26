<p align="center">
  <img src="./packages/web/public/argus-logo.png" alt="Argus" width="120" />
</p>

<h3 align="center">AI-native observability that replaces dashboards with conversation</h3>

<p align="center">
  <a href="https://github.com/precious112/Argus/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/node-%3E%3D18-green.svg" alt="Node.js" />
  <img src="https://img.shields.io/badge/docker-ready-blue.svg" alt="Docker" />
  <a href="https://github.com/precious112/Argus/stargazers"><img src="https://img.shields.io/github/stars/precious112/Argus?style=social" alt="GitHub Stars" /></a>
  <a href="https://github.com/precious112/Argus/issues"><img src="https://img.shields.io/github/issues/precious112/Argus" alt="GitHub Issues" /></a>
</p>

<p align="center">
  Argus is an open-source observability platform with a built-in AI agent that monitors your infrastructure, investigates anomalies autonomously, and proposes fixes — all through a chat interface. Think Datadog + ChatGPT, self-hosted and under your control.
</p>

---

<!-- REPLACE WITH DEMO VIDEO WHEN READY -->
![Argus Dashboard](https://raw.githubusercontent.com/precious112/Pstore_backend/refs/heads/master/media/media/Screenshot%202026-02-23%20at%207.27.19%20AM.png)

## Why Argus

- **Chat, don't dashboard** — Ask questions in natural language instead of writing PromQL or building Grafana panels
- **Autonomous investigation** — AI agent auto-investigates anomalies using a ReAct loop with 18+ tools, then proposes fixes
- **Full-stack observability** — Logs, metrics, traces, errors, and security in one place
- **Human-in-the-loop** — The agent proposes actions; you approve before anything executes
- **Cost-controlled AI** — Token budgets with daily/hourly limits prevent runaway LLM spending
- **LLM-agnostic** — Works with OpenAI, Anthropic, and Gemini — swap providers with one config change

## Features

### AI Agent
ReAct reasoning loop with 18+ tools for autonomous investigation. The agent reads logs, queries metrics, traces requests, correlates errors, and proposes remediation actions — all with your approval before execution.

### System Monitoring
CPU, memory, disk, network metrics. Process crash detection, OOM kills, resource exhaustion alerts. Collected automatically with zero configuration.

### Application Tracing
Distributed tracing with W3C trace context propagation. Automatic span creation for HTTP requests, database calls, and external dependencies. Error grouping with breadcrumb trails.

### Security Scanning
Brute-force login detection, open port scanning, suspicious process identification, and file permission auditing. Security events feed directly into the AI agent for correlation.

### Smart Alerting
Rules engine with Slack, email, and webhook delivery. AI-enhanced alert summaries that tell you *why* something matters, not just that a threshold was crossed.

### Token Budget Management
Daily and hourly token limits, priority reserves for critical investigations, and a cost analytics dashboard. Stay in control of LLM spending.

## Quick Start

### Single Image (Recommended)

A single unified image bundles the agent server and web UI together:

```bash
docker run -d --name argus \
  -p 7600:7600 -p 3000:3000 \
  -e ARGUS_LLM__PROVIDER=openai \
  -e ARGUS_LLM__API_KEY=your-api-key-here \
  -e ARGUS_LLM__MODEL=gpt-4o \
  -e ARGUS_PUBLIC_URL=http://your-server-ip:7600 \
  -e ARGUS_HOST_ROOT=/host \
  -v argus_data:/data \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:ro \
  -v /var/log:/host/var/log:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --pid=host \
  --privileged \
  --restart unless-stopped \
  ghcr.io/precious112/argus:latest
```

Replace `your-server-ip` with your server's external IP address (e.g. `104.198.209.149`).

> **Firewall / VPC:** Make sure ports **3000** and **7600** are open for TCP ingress in your cloud provider's firewall or VPC security group settings (e.g. GCP firewall rules, AWS security groups, Azure NSGs) — otherwise you won't be able to reach the UI or API from your browser.

- **Web UI:** open `http://your-server-ip:3000` in your browser
- **Agent API:** `http://your-server-ip:7600` from your browser

> **Note:** If you only need to interact with the API from within the server itself (e.g. `curl`, scripts, SDK calls), you can use `http://localhost:7600` directly — no firewall changes or `ARGUS_PUBLIC_URL` needed for that.

For Docker Compose (reads from `.env` file automatically):

```bash
export ARGUS_LLM_API_KEY=your-api-key-here
docker compose -f docker/docker-compose.unified.yml up -d
```

| Variable | Default | Description |
|----------|---------|-------------|
| `ARGUS_LLM__PROVIDER` | `openai` | LLM provider: `openai`, `anthropic`, `gemini` |
| `ARGUS_LLM__API_KEY` | — | **Required.** API key for your LLM provider |
| `ARGUS_LLM__MODEL` | `gpt-4o` | Model name |
| `ARGUS_PUBLIC_URL` | — | Set for remote access, e.g. `http://192.168.1.50:7600` |
| `ARGUS_CORS_ORIGINS` | auto | Custom CORS origins (auto-set when `ARGUS_PUBLIC_URL` is used) |

### Multi-Container Setup

Alternatively, run agent and web as separate containers:

```bash
# Set your LLM API key
export ARGUS_LLM_API_KEY=your-api-key-here

# Start Argus
docker compose up -d

# Open the web UI
open http://localhost:3000
```

### With Example Apps

Spin up Argus alongside instrumented Python and Node.js apps that generate realistic traffic:

```bash
export ARGUS_LLM_API_KEY=your-api-key-here
docker compose --profile test up -d
```

### Local Development

```bash
# Install all dependencies
make install

# Start the agent server (terminal 1)
make dev

# Start the web UI (terminal 2)
make dev-web

# Run tests
make test
```

## SDK Integration

Instrument your apps in minutes with the Python and Node.js SDKs.

### Python

```bash
pip install argus-ai-sdk
```

```python
import argus
from argus.middleware.fastapi import ArgusMiddleware

argus.init(
    server_url="http://localhost:7600",
    service_name="my-app",
    runtime_metrics=True,
    auto_instrument=True,
)

app = FastAPI()
app.add_middleware(ArgusMiddleware)

# Trace functions, capture errors, send custom events
@argus.decorators.trace("checkout")
async def checkout():
    argus.event("checkout_started", {"items": 3})
    try:
        process_payment()
    except Exception as e:
        argus.capture_exception(e)
```

### Node.js

```bash
npm install @argus-ai/node
```

```javascript
const Argus = require("@argus-ai/node");

Argus.init({
  serverUrl: "http://localhost:7600",
  serviceName: "my-app",
});
Argus.startRuntimeMetrics();
Argus.patchHttp();

const app = express();
app.use(Argus.argusMiddleware());

// Trace routes, capture errors, send custom events
app.get("/users", Argus.trace("get_users")((req, res) => {
  Argus.event("users_fetched", { count: results.length });
  res.json({ users: results });
}));
```

> See the full working examples in [`examples/python-fastapi/`](./examples/python-fastapi/) and [`examples/node-express/`](./examples/node-express/).

## Architecture

```
                    ┌──────────────────────────┐
                    │   Web UI (Next.js) :3000  │
                    │   CLI Client (Python)     │
                    └────────┬──┬───────────────┘
                         WebSocket  REST
                             │  │
┌──────────┐   ingest   ┌───▼──▼───────────────────────┐
│ SDKs     ├───────────►│   Agent Server (FastAPI) :7600│
│ Python   │            │                               │
│ Node.js  │            │  ┌─────────┐  ┌────────────┐  │
└──────────┘            │  │ Agent   │  │ Collectors │  │
                        │  │ ReAct   │  │ Metrics    │  │
                        │  │ Loop    │  │ Logs       │  │
                        │  │ 18+Tools│  │ Security   │  │
                        │  └────┬────┘  └─────┬──────┘  │
                        │       │             │         │
                        │  ┌────▼─────────────▼──────┐  │
                        │  │  Event Bus + Alert Engine│  │
                        │  └────┬────────────────────┘  │
                        │       │                       │
                        │  ┌────▼────────────────────┐  │
                        │  │ SQLite    │  DuckDB      │  │
                        │  │ (config)  │  (time-series)│  │
                        │  └──────────┴──────────────┘  │
                        └───────────────────────────────┘
```

## Configuration

Copy `argus.example.yaml` to `argus.yaml`, or use environment variables with the `ARGUS_` prefix:

```bash
export ARGUS_LLM__PROVIDER=openai      # openai, anthropic, gemini
export ARGUS_LLM__API_KEY=sk-...
export ARGUS_LLM__MODEL=gpt-4o
export ARGUS_DEBUG=true
```

See [`argus.example.yaml`](./argus.example.yaml) for all available options.

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Agent Server | Python, FastAPI, SQLAlchemy | Core AI agent, API, business logic |
| Web UI | Next.js, React, Tailwind CSS | Chat-first dashboard |
| CLI | Python, Rich | Terminal interface |
| Operational DB | SQLite | Config, sessions, alert rules |
| Time-Series DB | DuckDB | Metrics, logs, traces, events |
| Python SDK | Python | Application instrumentation |
| Node.js SDK | TypeScript | Application instrumentation |
| Deployment | Docker, Docker Compose | Production & development |

## Project Structure

```
argus/
├── packages/
│   ├── agent/          # Core agent server (Python/FastAPI)
│   ├── web/            # Next.js chat-first web UI
│   ├── cli/            # CLI/TUI client (Python)
│   ├── sdk-python/     # Python instrumentation SDK
│   ├── sdk-node/       # Node.js instrumentation SDK
│   └── shared/         # Shared protocol schemas
├── examples/
│   ├── python-fastapi/ # Instrumented FastAPI example app
│   └── node-express/   # Instrumented Express example app
├── docker-compose.yml  # Production deployment
├── Makefile            # Dev convenience commands
└── scripts/            # Dev and install scripts
```

## Contributing

Contributions are welcome! Please open an issue or submit a pull request on [GitHub](https://github.com/precious112/Argus).

## License

[MIT](./LICENSE)
