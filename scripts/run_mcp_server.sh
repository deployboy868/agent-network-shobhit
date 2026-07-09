#!/usr/bin/env bash
# Cursor MCP launcher — handles paths with spaces and loads .env via Python config.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
exec "$ROOT/.venv/bin/python" -m agent_network.mcp_server
