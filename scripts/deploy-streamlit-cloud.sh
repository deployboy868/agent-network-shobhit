#!/usr/bin/env bash
# Push to GitHub + print Streamlit Cloud deploy steps.
set -euo pipefail
cd "$(dirname "$0")/.."

APP_NAME="${1:-agent-network-demo}"

if ! command -v gh >/dev/null 2>&1; then
  echo "Installing GitHub CLI..."
  brew install gh
fi

if ! gh auth status >/dev/null 2>&1; then
  echo ""
  echo "GitHub login required (one time). Run:"
  echo "  gh auth login"
  echo "Then re-run: ./scripts/deploy-streamlit-cloud.sh"
  exit 1
fi

if [[ ! -d .git ]]; then
  git init
  git branch -M main
fi

git add -A
if git diff --cached --quiet; then
  echo "Nothing new to commit."
else
  git commit -m "Deploy Agent Social Network demo to Streamlit Cloud"
fi

if git remote get-url origin >/dev/null 2>&1; then
  echo "Pushing to existing origin..."
  git push -u origin main
else
  echo "Creating GitHub repo: $APP_NAME"
  gh repo create "$APP_NAME" --public --source=. --remote=origin --push --description "Agent Social Network internship demo"
fi

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo ""
echo "=== GitHub done: https://github.com/$REPO ==="
echo ""
echo "=== Streamlit Cloud (2 minutes) ==="
echo "1. Open: https://share.streamlit.io/"
echo "2. New app → pick repo: $REPO"
echo "3. Main file: streamlit_app.py"
echo "4. App URL: pick something like agent-network-shobhit"
echo "5. Advanced → Secrets — copy from .streamlit/secrets.toml.example"
echo "   (paste your real GROQ_API_KEY from .env)"
echo "6. Deploy → submit the https://YOUR-APP.streamlit.app link"
echo ""
echo "Opening Streamlit deploy page..."
open "https://share.streamlit.io/" 2>/dev/null || true
