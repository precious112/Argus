# Argus

**AI-Native Observability, Monitoring, and Security Platform**

Argus replaces traditional dashboards and manual configuration with an AI agent you interact with via chat. It reads server logs, collects system metrics, instruments applications via SDKs, and can execute fixes with your approval.

## Quick Start

### Docker (Recommended)

```bash
# Set your LLM API key
export ARGUS_LLM_API_KEY=your-api-key-here

# Start Argus
docker compose up -d

# Open the web UI
open http://localhost:3000
```

### Development

```bash
# Install dependencies
make install

# Start the agent server (terminal 1)
make dev

# Start the web UI (terminal 2)
make dev-web

# Run tests
make test
```

## Architecture

```
┌─────────────────────────────────┐
│     Web UI (Next.js) :3000      │
│     CLI Client (Python)         │
├─────────────────────────────────┤
│     Agent Server (FastAPI) :7600│
│  ┌─────────┐  ┌──────────────┐ │
│  │ Agent   │  │ Collectors   │ │
│  │ ReAct   │  │ (background) │ │
│  │ Loop    │  │              │ │
│  └─────────┘  └──────────────┘ │
├─────────────────────────────────┤
│  SQLite (operational)           │
│  DuckDB (time-series)           │
└─────────────────────────────────┘
```

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
├── docker-compose.yml  # Production deployment
├── Makefile            # Dev convenience commands
└── scripts/            # Dev and install scripts
```

## Configuration

Copy `argus.example.yaml` to `argus.yaml` and customize, or use environment variables with the `ARGUS_` prefix:

```bash
export ARGUS_LLM__PROVIDER=openai
export ARGUS_LLM__API_KEY=sk-...
export ARGUS_LLM__MODEL=gpt-4o
export ARGUS_DEBUG=true
```

## License

MIT
