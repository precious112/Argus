#!/usr/bin/env bash
# Setup script for Argus SaaS test runner on the VM.
#
# Run from the repo root:
#   chmod +x examples/saas-test-runner/setup.sh
#   ./examples/saas-test-runner/setup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

echo "=== Argus SaaS Test Runner Setup ==="
echo "Repo root: $REPO_ROOT"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

echo "Activating venv..."
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "Installing Argus SDK (editable)..."
pip install -e "$REPO_ROOT/packages/sdk-python"

echo "Installing test runner requirements..."
pip install -r "$REPO_ROOT/examples/saas-test-runner/requirements.txt"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Set environment variables (or create .env and source it):"
echo "     export ARGUS_URL=http://<MAC_IP>:80"
echo "     export ARGUS_API_KEY=argus_prod_xxxxx"
echo "     export ARGUS_WEBHOOK_SECRET=<secret>"
echo ""
echo "  2. Start the app (terminal 1):"
echo "     cd $REPO_ROOT/examples/saas-test-runner"
echo "     $VENV_DIR/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000"
echo ""
echo "  3. Start the test runner (terminal 2):"
echo "     cd $REPO_ROOT/examples/saas-test-runner"
echo "     $VENV_DIR/bin/python test_runner.py"
