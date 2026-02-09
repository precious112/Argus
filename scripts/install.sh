#!/usr/bin/env bash
# One-line install script for development setup
set -e

echo "=== Installing Argus Development Environment ==="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3.11+ is required"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python version: $PYTHON_VERSION"

# Install uv if not present
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# Install Python packages
echo "Installing agent dependencies..."
cd packages/agent
uv venv
uv pip install -e ".[dev,all-providers]"
cd ../..

echo "Installing CLI dependencies..."
cd packages/cli
uv pip install -e ".[dev]"
cd ../..

# Install Node.js packages
if command -v node &> /dev/null; then
    echo "Installing web UI dependencies..."
    cd packages/web && npm install && cd ../..

    echo "Installing Node.js SDK dependencies..."
    cd packages/sdk-node && npm install && cd ../..
else
    echo "Warning: Node.js not found. Skipping web UI and Node SDK setup."
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Quick start:"
echo "  make dev       # Start agent server"
echo "  make dev-web   # Start web UI (in another terminal)"
echo "  make test      # Run tests"
echo ""
