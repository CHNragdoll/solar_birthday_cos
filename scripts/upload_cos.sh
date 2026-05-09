#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ICS_FILE="$PROJECT_DIR/private_data/birthdays.ics"
ENV_FILE="$PROJECT_DIR/private_data/cos.env"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

BUCKET="${COS_BUCKET:-}"
REGION="${COS_REGION:-}"
OBJECT_KEY="${COS_OBJECT_KEY:-}"

if [[ -z "$BUCKET" || -z "$REGION" || -z "$OBJECT_KEY" ]]; then
  echo "[ERROR] missing COS config."
  echo "[HINT] fill private_data/cos.env (COS_BUCKET/COS_REGION/COS_OBJECT_KEY)."
  exit 1
fi

if ! command -v coscli >/dev/null 2>&1; then
  echo "[ERROR] coscli not found."
  echo "[HINT] Upload manually in Tencent COS console, or install/configure COSCLI first."
  exit 1
fi

if [[ ! -f "$ICS_FILE" ]]; then
  echo "[ERROR] missing file: $ICS_FILE"
  echo "[HINT] run: scripts/generate.sh"
  exit 1
fi

coscli cp "$ICS_FILE" "cos://$BUCKET/$OBJECT_KEY" \
  --region "$REGION" \
  --headers "Content-Type:text/calendar; charset=utf-8"

echo "[OK] uploaded: cos://$BUCKET/$OBJECT_KEY"
echo "https://$BUCKET.cos.$REGION.myqcloud.com/$OBJECT_KEY"
echo "[NOTICE] 上传覆盖后请手动检查对象权限为：公有读私有写"
