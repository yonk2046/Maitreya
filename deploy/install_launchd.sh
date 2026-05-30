#!/usr/bin/env bash
# Install / uninstall the SCD Engine daily launchd job (macOS only).
#
# Usage:
#   bash deploy/install_launchd.sh install
#   bash deploy/install_launchd.sh uninstall
#   bash deploy/install_launchd.sh status
#
# Idempotent. Re-running install overwrites the existing plist.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
AI_STOCK_DIR="$(cd "$HERE/.." && pwd)"
TEMPLATE="$HERE/com.scd.daily.plist.template"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.scd.daily.plist"
PLIST_TARGET="$LAUNCH_AGENT_DIR/$PLIST_NAME"
LABEL="com.scd.daily"

case "${1:-help}" in
  install)
    if [[ "$(uname)" != "Darwin" ]]; then
      echo "[install] non-macOS detected; launchd is macOS-only. Use cron on Linux." >&2
      exit 2
    fi
    PYTHON_BIN="$(command -v python3)"
    if [[ -z "$PYTHON_BIN" ]]; then
      echo "[install] python3 not on PATH" >&2; exit 2
    fi
    mkdir -p "$LAUNCH_AGENT_DIR" "$AI_STOCK_DIR/reports/_daily_logs"
    sed -e "s|__AI_STOCK_DIR__|$AI_STOCK_DIR|g" \
        -e "s|__PYTHON__|$PYTHON_BIN|g" \
        "$TEMPLATE" > "$PLIST_TARGET"
    # Unload any existing job (ignore errors), then load.
    launchctl unload "$PLIST_TARGET" 2>/dev/null || true
    launchctl load "$PLIST_TARGET"
    echo "[install] installed $PLIST_TARGET"
    echo "[install] python: $PYTHON_BIN"
    echo "[install] cwd:    $AI_STOCK_DIR"
    echo "[install] schedule: weekdays 19:00 local"
    echo "[install] to run now: launchctl start $LABEL"
    ;;

  uninstall)
    if [[ -f "$PLIST_TARGET" ]]; then
      launchctl unload "$PLIST_TARGET" 2>/dev/null || true
      rm "$PLIST_TARGET"
      echo "[uninstall] removed $PLIST_TARGET"
    else
      echo "[uninstall] no plist at $PLIST_TARGET — nothing to do"
    fi
    ;;

  status)
    if [[ -f "$PLIST_TARGET" ]]; then
      echo "[status] plist present: $PLIST_TARGET"
      launchctl list | grep -E "$LABEL" || echo "[status] not currently loaded"
    else
      echo "[status] not installed (no plist at $PLIST_TARGET)"
    fi
    ;;

  *)
    cat <<USAGE
SCD daily launchd manager.
  install     — render template, install ~/Library/LaunchAgents/com.scd.daily.plist, load it
  uninstall   — unload + remove the plist
  status      — show whether the agent is installed / loaded
USAGE
    exit 0
    ;;
esac
