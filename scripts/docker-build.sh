#!/usr/bin/env bash
# Build the Agent Network Teams service image.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on PATH." >&2
  echo "Install Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/" >&2
  exit 1
fi

TAG="${1:-agent-network:latest}"
echo "Building ${TAG} ..."
docker build -t "${TAG}" .
echo "Done. Run: ./scripts/docker-run.sh"
echo "       Demo UI → http://localhost:8501"
