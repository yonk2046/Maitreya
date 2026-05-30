"""Minimal read-only loader for the temporal toolkit.

Separate from `viewer.data` because the viewer module imports streamlit at
module load. CLI tools should not require streamlit, so this module
duplicates the small subset of loader logic the toolkit needs.

All functions are pure — no caching, no mutation. The pipeline already
caches at OS-level via the filesystem; the toolkit re-reads every call.
This keeps determinism trivial to reason about.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent.parent  # tools/temporal/ → tools/ → Ai stock/
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

REPORTS_DIR = _AI_STOCK / "reports"
INDEX_FILE = REPORTS_DIR / "index.json"


def load_index() -> dict[str, Any]:
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def load_snapshot(date_key: str) -> dict[str, Any]:
    return json.loads((REPORTS_DIR / f"{date_key}.json").read_text(encoding="utf-8"))


def is_iso_date(s: str) -> bool:
    try:
        dt.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def real_dates() -> list[str]:
    """Sorted ISO date keys present in the index (skips *.example)."""
    return sorted(k for k in load_index().get("snapshots", {}).keys() if is_iso_date(k))


def universe_for_date(date_key: str) -> list[str]:
    """Sorted tickers present in one snapshot."""
    snap = load_snapshot(date_key)
    return sorted(s["ticker"] for s in snap.get("stocks", []))


def stock_record(snap: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    """Return the StockRecord for one ticker in a snapshot, or None if absent."""
    for s in snap.get("stocks", []):
        if s.get("ticker") == ticker:
            return s
    return None


def ticker_observations(ticker: str) -> list[dict[str, Any]]:
    """Walk every real date in chronological order. Return one dict per date.

    Each dict:
      {date, present, tier, composite_score, rank, current_price,
       change_pct, volume, main_force_buy, top5_count, name}
    Missing/abstained fields are None.
    """
    rows: list[dict[str, Any]] = []
    for d in real_dates():
        snap = load_snapshot(d)
        rec = stock_record(snap, ticker)
        rows.append({
            "date":             d,
            "present":          rec is not None,
            "tier":             rec.get("tier") if rec else None,
            "composite_score":  rec.get("composite_score") if rec else None,
            "rank":             None,  # not stored in StockRecord — set below if available
            "current_price":    rec.get("current_price") if rec else None,
            "change_pct":       rec.get("change_pct") if rec else None,
            "volume":           rec.get("volume") if rec else None,
            "main_force_buy":   rec.get("main_force_buy") if rec else None,
            "top5_count":       len(rec.get("top5_branches", [])) if rec else 0,
            "name":             rec.get("name") if rec else None,
        })
    return rows


def stocks_for_date(date_key: str) -> list[dict[str, Any]]:
    """Return the full list of StockRecord dicts for one date (a list, not a generator)."""
    return list(load_snapshot(date_key).get("stocks", []))


def audit_events_for_date(date_key: str) -> list[dict[str, Any]]:
    return list(load_snapshot(date_key).get("audit_log", []))
