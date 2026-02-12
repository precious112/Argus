# Argus Agent - Production Dockerfile
FROM python:3.12-slim

# System dependencies for monitoring
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps iproute2 curl util-linux && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy source first (pyproject.toml needs src/ present for editable install)
COPY packages/agent/pyproject.toml packages/agent/README.md ./
COPY packages/agent/src/ ./src/

# Install dependencies
RUN uv pip install --system ".[all-providers]"

# Create data directory
RUN mkdir -p /data

ENV ARGUS_STORAGE__DATA_DIR=/data
EXPOSE 7600

CMD ["python", "-m", "uvicorn", "argus_agent.main:app", \
     "--host", "0.0.0.0", "--port", "7600"]
