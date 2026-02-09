#!/usr/bin/env bash
# Development startup script - runs agent server and web UI concurrently
set -e

echo "=== Argus Development Server ==="
echo ""

# Check dependencies
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "Error: Node.js is not installed."
    exit 1
fi

# Install if needed
if [ ! -d "packages/web/node_modules" ]; then
    echo "Installing web dependencies..."
    cd packages/web && npm install && cd ../..
fi

# Start agent server
echo "Starting agent server on :7600..."
cd packages/agent
uvicorn argus_agent.main:app --reload --reload-dir src --host 0.0.0.0 --port 7600 &
AGENT_PID=$!
cd ../..

# Start web UI
echo "Starting web UI on :3000..."
cd packages/web
npm run dev &
WEB_PID=$!
cd ../..

echo ""
echo "Agent: http://localhost:7600"
echo "Web UI: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop all services."

# Cleanup on exit
trap "kill $AGENT_PID $WEB_PID 2>/dev/null; exit 0" INT TERM

wait
