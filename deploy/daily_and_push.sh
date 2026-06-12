#!/bin/bash
# Maitreya daily pipeline + git push  (PRIMARY writer)
# Called by launchd every weekday at 19:00 Asia/Taipei.
# GitHub Actions (daily.yml) is the BACKUP writer: it runs at 20:00 Taipei
# and skips itself when this script already produced today's snapshot.
#
# OPS-1 rewrite 2026-06-12:
#   - pull --rebase BEFORE running (was: merge -X ours, which silently
#     overwrote remote changes including code fixes)
#   - pipeline failure now ABORTS the commit (was: || echo … then commit
#     anyway — same masking we removed from daily.yml)
#   - push retries with pull --rebase up to 3 times (was: single push,
#     non-fast-forward → crashed mid-commit, stale .git/*.lock files)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_STOCK="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$AI_STOCK"

echo "[daily_and_push] $(date '+%Y-%m-%d %H:%M:%S') starting"

# ── 0. Clean any stale lock from a previously crashed run ──────────────────
# Safe at this point: launchd serializes our own runs, and we haven't
# started any git operation yet in THIS run.
for lock in .git/index.lock .git/HEAD.lock; do
    if [ -f "$lock" ]; then
        echo "[daily_and_push] removing stale $lock (previous run crashed?)"
        rm -f "$lock"
    fi
done

# ── 1. Sync with remote BEFORE generating anything ─────────────────────────
# --autostash: the working tree usually has untracked/modified __pycache__
# noise; a plain rebase would refuse to run on a dirty tree.
git fetch origin main
if ! git rebase --autostash origin/main; then
    git rebase --abort || true
    echo "[daily_and_push] ❌ rebase onto origin/main failed — manual fix needed; aborting (no data generated, nothing lost)"
    exit 1
fi

# ── 2. Market pulse (non-blocking: fails on non-trading days) ───────────────
python3 tools/fetch_market_pulse.py || echo "[daily_and_push] fetch_market_pulse failed (non-trading day?)"

# ── 3. Daily pipeline — failure ABORTS, we do not commit suspect data ──────
if ! python3 -m tools.daily; then
    echo "[daily_and_push] ❌ tools.daily failed — NOT committing. Check reports/_daily_logs/."
    exit 1
fi

# ── 4. Commit and push (retry on race with the GHA backup) ─────────────────
git config user.name  "maitreya-bot"
git config user.email "maitreya-bot@users.noreply.github.com"

git add data/ reports/

if git diff --staged --quiet; then
    echo "[daily_and_push] no changes to commit"
else
    DATE=$(date -u +%Y-%m-%d)
    git commit -m "data: daily pipeline ${DATE} [skip ci]"
    pushed=0
    for attempt in 1 2 3; do
        if git push origin main; then
            pushed=1
            echo "[daily_and_push] pushed successfully (attempt ${attempt})"
            break
        fi
        echo "[daily_and_push] push rejected (attempt ${attempt}) — rebasing onto remote and retrying"
        git fetch origin main
        if ! git rebase --autostash origin/main; then
            git rebase --abort || true
            echo "[daily_and_push] ❌ rebase during push-retry failed — manual fix needed"
            exit 1
        fi
    done
    if [ "$pushed" -ne 1 ]; then
        echo "[daily_and_push] ❌ push failed after 3 attempts"
        exit 1
    fi
fi

echo "[daily_and_push] done"
