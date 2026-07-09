#!/usr/bin/env bash
# Reset all persisted twin state for a clean demo test run.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

echo "=== Fresh testing reset ==="

PYTHONPATH=. "$PY" -m agent_network.demo.clear_agent_memory

if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx agent-network; then
  echo ""
  echo "Clearing Docker volume (/data)..."
  docker exec agent-network python -m agent_network.demo.clear_agent_memory
  echo "Docker reset done."
else
  echo ""
  echo "Docker container not running — host reset only."
fi

echo ""
echo "Ready for fresh testing."
