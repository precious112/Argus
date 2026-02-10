#!/usr/bin/env bash
set -euo pipefail

# Argus Deployment Script
# Usage: bash scripts/deploy.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# --- Prerequisites ---
info "Checking prerequisites..."

command -v docker >/dev/null 2>&1 || error "docker is not installed"
command -v docker compose >/dev/null 2>&1 || error "docker compose is not available"

if ! docker info >/dev/null 2>&1; then
    error "Docker daemon is not running"
fi

# --- Environment ---
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        warn ".env file not found. Copying from .env.example"
        cp .env.example .env
        warn "Please edit .env with your API key and host, then re-run this script."
        exit 1
    else
        error ".env file not found and no .env.example available"
    fi
fi

# Validate required vars
source .env
if [ -z "${ARGUS_LLM_API_KEY:-}" ] || [ "${ARGUS_LLM_API_KEY:-}" = "sk-your-api-key-here" ]; then
    warn "ARGUS_LLM_API_KEY is not set in .env — AI features will be disabled"
fi

# --- Build ---
info "Building Docker images..."
docker compose build --parallel

# --- Deploy ---
info "Starting services..."
docker compose up -d

# --- Health Check ---
info "Waiting for services to start..."
MAX_RETRIES=30
RETRY=0
AGENT_URL="http://localhost:7600/api/v1/health"

while [ $RETRY -lt $MAX_RETRIES ]; do
    if curl -sf "$AGENT_URL" >/dev/null 2>&1; then
        info "Agent server is healthy!"
        break
    fi
    RETRY=$((RETRY + 1))
    sleep 2
done

if [ $RETRY -eq $MAX_RETRIES ]; then
    warn "Agent server did not respond within 60s. Check logs:"
    echo "  docker compose logs argus --tail 50"
else
    info "Argus is running!"
    echo ""
    echo "  Agent API: http://localhost:7600/api/v1/health"
    echo "  Web UI:    http://localhost:3000"
    echo ""
    echo "  Logs:      docker compose logs -f"
    echo "  Stop:      docker compose down"
fi
