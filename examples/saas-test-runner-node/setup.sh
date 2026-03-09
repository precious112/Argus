#!/usr/bin/env bash
# Setup script for Argus SaaS test runner (Node) on the VM.
#
# Run from the repo root:
#   chmod +x examples/saas-test-runner-node/setup.sh
#   ./examples/saas-test-runner-node/setup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNNER_DIR="$REPO_ROOT/examples/saas-test-runner-node"
SDK_DIR="$REPO_ROOT/packages/sdk-node"

echo "=== Argus SaaS Test Runner (Node) Setup ==="
echo "Repo root: $REPO_ROOT"

# Build the Node SDK from source
echo "Building Argus Node SDK..."
cd "$SDK_DIR"
npm install
npm run build

# Install test runner dependencies + link local SDK
echo "Installing test runner dependencies..."
cd "$RUNNER_DIR"
npm install
npm install "$SDK_DIR"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Set environment variables (or create .env from .env.example):"
echo "     cp .env.example .env"
echo "     # Edit .env with your values:"
echo "     #   ARGUS_URL=http://<MAC_IP>:80"
echo "     #   ARGUS_API_KEY=argus_prod_xxxxx"
echo "     #   ARGUS_WEBHOOK_SECRET=<secret>"
echo ""
echo "  2. Start the app (terminal 1):"
echo "     cd $RUNNER_DIR"
echo "     node app.js"
echo ""
echo "  3. Start the test runner (terminal 2):"
echo "     cd $RUNNER_DIR"
echo "     node test_runner.js"
