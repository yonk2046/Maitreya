#!/bin/bash
# Maitreya daily pipeline + git push
# Called by launchd every weekday at 19:00
# Also called by GitHub Actions as backup

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_STOCK="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$AI_STOCK"

echo "[daily_and_push] $(date '+%Y-%m-%d %H:%M:%S') starting"

# Sync with remote — use merge with ours strategy to avoid market_pulse.json conflicts
git fetch origin main
git merge -X ours origin/main --no-edit || echo "[daily_and_push] merge failed, continuing"

# Fetch market pulse (TAIEX / TX futures / 三大法人)
python3 tools/fetch_market_pulse.py || echo "[daily_and_push] fetch_market_pulse failed (non-trading day?)"

# Run daily pipeline (allow replay mismatch errors)
python3 -m tools.daily || echo "[daily_and_push] tools.daily exited non-zero (replay mismatch?)"

# Commit and push
git config user.name  "maitreya-bot"
git config user.email "maitreya-bot@users.noreply.github.com"

git add data/ reports/ || true

if git diff --staged --quiet; then
    echo "[daily_and_push] no changes to commit"
else
    DATE=$(date -u +%Y-%m-%d)
    git commit -m "data: daily pipeline ${DATE} [skip ci]"
    git push origin main
    echo "[daily_and_push] pushed successfully"
fi

echo "[daily_and_push] done"
