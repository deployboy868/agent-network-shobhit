#!/usr/bin/env bash
# Deploy permanent demo to Render (no laptop required).
# URL: https://agent-network-demo.onrender.com
set -euo pipefail

REPO_URL="https://github.com/deployboy868/agent-network-shobhit"
BLUEPRINT_URL="https://dashboard.render.com/blueprint/new?repo=${REPO_URL}"

echo "=== Agent Network — permanent cloud deploy ==="
echo ""
echo "Streamlit Cloud is currently broken (platform-wide CSS error)."
echo "Use Render instead — free, permanent onrender.com URL."
echo ""
echo "1. Open this link (log in with GitHub if asked):"
echo "   ${BLUEPRINT_URL}"
echo ""
echo "2. When prompted, set GROQ_API_KEY to your Groq key."
echo "3. Click Apply / Deploy."
echo "4. Wait ~5 min. Your link will be:"
echo "   https://agent-network-demo.onrender.com"
echo ""
echo "First visit after idle may take ~30s to wake — that is normal on free tier."
echo ""

if command -v open >/dev/null 2>&1; then
  open "${BLUEPRINT_URL}"
fi
