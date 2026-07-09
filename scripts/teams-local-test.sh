#!/usr/bin/env bash
# Local MS Teams bot test — prerequisites check + quick start hints.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Agent Network — Teams local test ==="
echo ""

missing=0
check_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "  MISSING  $name"
    missing=1
  else
    echo "  ok       $name"
  fi
}

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "Required in .env:"
check_env MICROSOFT_APP_ID
check_env MICROSOFT_APP_PASSWORD
check_env GROQ_API_KEY
if [[ -z "${TEAMS_USER_MAP:-}" ]]; then
  echo "  WARN     TEAMS_USER_MAP (recommended — maps your Teams email to emp-manager)"
fi
echo ""

if ! curl -sf http://localhost:3978/healthz >/dev/null 2>&1; then
  echo "Teams API not reachable on :3978"
  echo "  Start: ./scripts/docker-run.sh"
  echo "    or:  PYTHONPATH=. python -m agent_network.teams.app"
  missing=1
else
  echo "Teams API healthy: http://localhost:3978/healthz"
fi
echo ""

if [[ "$missing" -ne 0 ]]; then
  echo "Fix the items above, then:"
fi

cat <<'EOF'
Next steps:
  1. Expose :3978 with HTTPS (Microsoft dev tunnel recommended):
       devtunnel user login
       devtunnel host -p 3978 --allow-anonymous
     Copy the https URL (e.g. https://xxxx-3978.devtunnels.ms)

  2. Azure Portal → your Azure Bot → Configuration
     Messaging endpoint: https://<tunnel-host>/api/messages

  3. Package Teams app:
       ./scripts/teams-package-manifest.sh <tunnel-host-without-https>

  4. Teams → Apps → Manage your apps → Upload custom app → teams_app/manifest.zip

  5. Open a 1:1 chat with "Agent Network Twin"
     - Default twin: Demo Manager (DEFAULT_TWIN_ID=emp-manager)
     - Switch: "talk to demo intern"
     - Set TEAMS_USER_MAP so ticket actions know who you are:
       TEAMS_USER_MAP={"you@sprinklr.com":"emp-manager"}

Logs: docker logs -f agent-network
EOF
