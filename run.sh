#!/usr/bin/env bash
# ==============================================================================
# Runner script for Autonomous GitHub Agent
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure dependencies are installed
if ! python3 -c "import httpx, pydantic, rich, dotenv" &>/dev/null; then
    echo "Installing required dependencies..."
    python3 -m pip install -q httpx pydantic rich python-dotenv
fi

# Execute CLI
python3 -m src.cli "$@"
