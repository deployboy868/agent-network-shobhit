#!/usr/bin/env bash
# Run demo UI + Teams API in Docker (requires .env).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill in values." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on PATH." >&2
  exit 1
fi

echo "Building image..."
docker build -t agent-network:latest .

docker rm -f agent-network 2>/dev/null || true

docker run -d --name agent-network \
  -p 3978:3978 \
  -p 8501:8501 \
  --add-host=host.docker.internal:host-gateway \
  --env-file .env \
  -e TWIN_MEMORY_DB=/data/twin-memory.db \
  -e TWIN_AUDIT_LOG=/data/twin-audit.jsonl \
  -v agent-network-data:/data \
  agent-network:latest

echo ""
echo "Demo chat UI:  http://localhost:8501"
echo "Teams API:     http://localhost:3978/healthz"
echo "Logs:          docker logs -f agent-network"
