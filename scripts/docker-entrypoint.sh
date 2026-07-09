#!/bin/sh
# Teams API (3978) + Streamlit demo UI (8501) in one container.
set -e

python -m agent_network.teams.app &
API_PID=$!

cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

exec streamlit run agent_network/demo/twin_chat_app.py \
  --server.port=8501 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false
