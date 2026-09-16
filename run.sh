#!/usr/bin/env bash
# ==============================================================================
# Runner script for Autonomous GitHub Agent
# ==============================================================================

set -eu -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

AGENT_PYTHON="${AGENT_PYTHON:-$SCRIPT_DIR/.venv/bin/python}"
if [[ ! -x "$AGENT_PYTHON" ]]; then
    echo "Create the project environment first: python3 -m venv .venv && .venv/bin/python -m pip install -e ."
    exit 1
fi

# Execute CLI
exec "$AGENT_PYTHON" -m src.cli "$@"
