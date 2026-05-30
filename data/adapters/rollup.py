"""Rollup adapter — backfill historical dates from existing
`data/snapshots/<latest>.json` multi-day rollup.

This adapter is used ONLY for backfilling history. For live ingest of today's
date, use `data.adapters.legacy.adapt_legacy()` which reads `data/today.json`.

The rollup stores per-day `buyList[]` (Stage 1 candidates) plus partial
stage2 results, but lacks branch-level detail for historical days. Therefore:
  - top5_branches is empty for historical snapshots
  - main_force_cost / total_buy_vol abstained
  - branches DATA_WARNING emitted

This adapter is deterministic given the same rollup file.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import unicodedata
from typing import Any

from core.hashing import file_sha256
from data.adapters.contract import validate_adapter_output
from data.adapters.legacy import legacy_paths, _utc_iso


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _latest_rollup_path() -> pathlib.Path:
    paths = legacy_paths()
    snaps = sorted(paths["snapshots"].glob("*.json"))
    if not snaps:
        raise FileNotFoundError(f"no rollup snapshots in {paths['snapshots']}")
    return snaps[-1]


def adapt_rollup(date: str, *, rollup_path: pathlib.Path | None = None) -> dict[str, Any]:
    """Read a historical date out of the latest rollup snapshot.

    Args:
        date: target YYYY-MM-DD. Must exist as a key in rollup.days{}.
        rollup_path: override which rollup file to read (default: latest in data/snapshots/).

    Returns the same shape as legacy.adapt_legacy().
    """
    if rollup_path is None:
        rollup_path = _latest_rollup_path()
    rollup_raw = rollup_path.read_text(encoding="utf-8")
    rollup = json.loads(rollup_raw)
    rollup_sha = file_sha256(rollup_path)
    rollup_mtime = _utc_iso(rollup_path.stat().st_mtime)

    days = rollup.get("days", {}) or {}
    if date not in days:
        available = sorted(days.keys())
        raise ValueError(
            f"date {date} not found in rollup {rollup_path.name}; "
            f"available: {available}"
        )
    day = days[date]
    buy_list = day.get("buyList", []) or []
    stage2_results = day.get("stage2", {}) or {}
    vol_rows = day.get("volRows", []) or []
    funnel = day.get("funnel")
    sess_meta = day.get("meta", {}) or {}

    audit_events: list[dict] = []

    # Build per-ticker raw_inputs from buyList
    raw_inputs_per_ticker: dict[str, dict] = {}
    for row in buy_list:
        ticker = str(row.get("code", "")).strip()
        if not ticker:
            continue
        ri: dict[str, Any] = {
            "ticker":          ticker,
            "name":            _nfc(str(row.get("name", ""))),
            "rank":            row.get("rank"),
            "is_etf":          bool(row.get("isETF", False)),
            "current_price":   row.get("close") or None,  # 0 → null (no real data)
            "change_pct":      row.get("chgPct"),
            "buy_vol_lots":    row.get("buyVol") or 0,
            "note":            row.get("note", ""),
            "stage2_verdict_legacy": row.get("stage2Verdict"),
            "sector_legacy":   row.get("sector"),
        }
        # Stage 2 detail if present
        if ticker in stage2_results:
            s2 = stage2_results[ticker]
            ri["legacy_stage2"] = {
                "days":         s2.get("days"),
                "v1":           s2.get("v1"),
                "v2":           s2.get("v2"),
                "v3":           s2.get("v3"),
                "diff":         s2.get("diff"),
                "totalAmt":     s2.get("totalAmt"),
                "totalVol":     s2.get("totalVol"),
                "price":        s2.get("price"),
                "cost":         s2.get("cost"),
                "verdict":      s2.get("verdict"),
            }
        # Backfilled data has no branches detail
        ri["top5_branches"] = []
        ri["_branches_present"] = False
        ri["_backfilled"] = True
        raw_inputs_per_ticker[ticker] = ri

    universe = sorted(raw_inputs_per_ticker.keys())

    # Provenance — raw_file uses the canonical "data/snapshots/<filename>" form
    # so that replay against the archived copy of this same file produces an
    # identical provenance entry even though the bytes were read elsewhere.
    provenance_sources = {
        "legacy_rollup": {
            "dataset":         "SCD.legacy.rollup_snapshot",
            "url":             f"file://data/snapshots/{rollup_path.name}",
            "fetched_at":      rollup_mtime,
            "raw_file":        f"data/snapshots/{rollup_path.name}",
            "raw_sha256":      rollup_sha,
            "row_count":       len(buy_list),
            "vendor_id":       None,
            "report_date":     date,
            "data_lag_days":   None,   # rollup contains many dates; lag undefined
            "provides_fields": [
                "ticker", "name", "rank", "is_etf",
                "current_price", "change_pct", "buy_vol_lots",
                "legacy_stage2",
            ],
        },
    }

    audit_events.append({
        "ticker": None,
        "event": "INFO",
        "reason": (
            f"Backfilled from rollup {rollup_path.name} (date={date}); "
            f"top5_branches unavailable for historical day; "
            f"original_buyList_size={len(buy_list)} stage2_results={len(stage2_results)} "
            f"volRows={len(vol_rows)} funnel={funnel}"
        ),
        "step": "adapters.rollup.adapt_rollup",
    })

    # Note: many tickers' close = 0 in the rollup buyList (rank>=2 often empty)
    # — emit DATA_WARNING for each
    for ticker in universe:
        ri = raw_inputs_per_ticker[ticker]
        if ri.get("current_price") is None:
            audit_events.append({
                "ticker": ticker,
                "event": "DATA_WARNING",
                "reason": "current_price unavailable in rollup buyList (legacy field=0)",
                "step": "adapters.rollup.field_extract",
            })

    out = {
        "date":                  date,
        "raw_inputs_per_ticker": raw_inputs_per_ticker,
        "universe":              universe,
        "provenance_sources":    provenance_sources,
        "audit_events":          audit_events,
        "_rollup_meta": {
            "rollup_file":  rollup_path.name,
            "session_meta": sess_meta,
            "funnel":       funnel,
        },
    }
    validate_adapter_output(out, adapter_name="rollup.adapt_rollup")
    return out


def available_dates(rollup_path: pathlib.Path | None = None) -> list[str]:
    """List historical dates available in the rollup."""
    if rollup_path is None:
        rollup_path = _latest_rollup_path()
    rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
    return sorted(rollup.get("days", {}).keys())
