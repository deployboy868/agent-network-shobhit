#!/usr/bin/env bash
# Expose Streamlit demo (:8501) on a public HTTPS URL for user evaluation.
# Requires: Docker running (./scripts/docker-run.sh), cloudflared (brew install cloudflared)
set -euo pipefail
cd "$(dirname "$0")/.."

if ! curl -sf http://localhost:8501 >/dev/null 2>&1; then
  echo "Streamlit not reachable on :8501. Run: ./scripts/docker-run.sh" >&2
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Install cloudflared: brew install cloudflared" >&2
  exit 1
fi

echo "=== Public evaluation link ==="
echo "Keep this terminal open. URL appears below in ~10 seconds."
echo ""
exec cloudflared tunnel --url http://localhost:8501
