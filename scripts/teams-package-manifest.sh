#!/usr/bin/env bash
# Build teams_app/manifest.zip for sideloading into Microsoft Teams.
# Usage: ./scripts/teams-package-manifest.sh <bot-domain>
#   bot-domain = hostname only, e.g. abc123.devtunnels.ms (no https://)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Missing .env" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

APP_ID="${MICROSOFT_APP_ID:-}"
BOT_DOMAIN="${1:-}"

if [[ -z "$APP_ID" ]]; then
  echo "Set MICROSOFT_APP_ID in .env (from Azure Bot registration)." >&2
  exit 1
fi
if [[ -z "$BOT_DOMAIN" ]]; then
  echo "Usage: $0 <bot-domain>" >&2
  echo "  Example: $0 abc123-3978.devtunnels.ms" >&2
  exit 1
fi

BOT_DOMAIN="${BOT_DOMAIN#https://}"
BOT_DOMAIN="${BOT_DOMAIN%%/*}"

OUT_DIR="teams_app/_package"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

python3 - <<'PY'
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    raise SystemExit("Install Pillow: pip install pillow")

root = Path("teams_app/_package")
color = Image.new("RGB", (192, 192), (27, 31, 42))
color.save(root / "color.png")
outline = Image.new("RGBA", (32, 32), (27, 31, 42, 255))
outline.save(root / "outline.png")
print("Generated color.png (192x192) and outline.png (32x32)")
PY

sed -e "s/\${MICROSOFT_APP_ID}/${APP_ID}/g" \
    -e "s/\${BOT_DOMAIN}/${BOT_DOMAIN}/g" \
    teams_app/manifest.json > "$OUT_DIR/manifest.json"

(
  cd "$OUT_DIR"
  zip -q ../manifest.zip manifest.json color.png outline.png
)

echo "Created teams_app/manifest.zip"
echo "  App ID:  $APP_ID"
echo "  Domain:  $BOT_DOMAIN"
echo ""
echo "Upload: Teams → Apps → Manage your apps → Upload a custom app"
