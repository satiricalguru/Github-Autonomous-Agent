#!/usr/bin/env bash
# ==============================================================================
# Runner script for Autonomous GitHub Agent
# ==============================================================================

set -eu -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure dependencies are installed
if ! python3 -c "import httpx, pydantic, rich, dotenv" &>/dev/null; then
    echo "Installing required dependencies..."
    python3 -m pip install -q "httpx>=0.27.0" "pydantic>=2.7.0" "rich>=13.7.0" "python-dotenv>=1.0.0"
fi

# Execute CLI
python3 -m src.cli "$@"
