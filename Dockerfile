# Multi-stage build for Argus

# --- Stage 1: Build web UI ---
FROM node:22-alpine AS web-builder

WORKDIR /build/web
COPY packages/web/package.json packages/web/package-lock.json* ./
RUN npm install --frozen-lockfile 2>/dev/null || npm install
COPY packages/web/ ./
RUN npm run build

# --- Stage 2: Python agent ---
FROM python:3.12-slim AS agent

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install agent dependencies
COPY packages/agent/pyproject.toml ./
RUN uv pip install --system -e ".[all-providers]" 2>/dev/null || \
    uv pip install --system .

# Copy agent source
COPY packages/agent/src/ ./src/

# Copy built web UI into static directory
COPY --from=web-builder /build/web/.next/standalone ./web-standalone/
COPY --from=web-builder /build/web/.next/static ./web-standalone/.next/static/
COPY --from=web-builder /build/web/public ./web-standalone/public/

# Create data directory
RUN mkdir -p /data

ENV ARGUS_STORAGE__DATA_DIR=/data
ENV ARGUS_HOST_ROOT=""

EXPOSE 7600

CMD ["python", "-m", "uvicorn", "argus_agent.main:app", "--host", "0.0.0.0", "--port", "7600"]
