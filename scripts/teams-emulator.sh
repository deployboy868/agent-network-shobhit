#!/usr/bin/env bash
# Quick guide: Bot Framework Emulator without Azure credentials.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Bot Framework Emulator (no Azure) ==="
echo ""
echo "1. .env should have:"
echo "     BOT_EMULATOR_MODE=true"
echo "     MICROSOFT_APP_ID=          (leave empty)"
echo "     MICROSOFT_APP_PASSWORD=    (leave empty)"
echo "     DEFAULT_REQUESTER_ID=emp-manager   # or emp-intern"
echo ""
echo "2. Start API (pick one):"
echo "     ./scripts/docker-run.sh"
echo "     PYTHONPATH=. python -m agent_network.teams.app"
echo ""
echo "3. Open Bot Framework Emulator → Open Bot"
echo "     Bot URL:  http://localhost:3978/api/messages"
echo "     Microsoft App ID:     (leave blank)"
echo "     Microsoft App Password: (leave blank)"
echo ""
echo "4. Demo commands in chat (no restart needed):"
echo "     talk to demo manager     # whose twin"
echo "     act as demo assignee     # who you are (behaviour + memory)"
echo "     session                  # show current twin + persona"
echo "     help demo"
echo ""
echo "5. Example flows:"
echo "     act as demo intern → talk to demo manager → create ticket"
echo "     act as demo manager → talk to demo manager → what happened while away?"
echo ""
if curl -sf http://localhost:3978/healthz >/dev/null 2>&1; then
  echo "Status: :3978 is up"
else
  echo "Status: :3978 not running — start docker or teams.app first"
fi
