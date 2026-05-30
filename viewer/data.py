"""Cached read-only loaders for the viewer.

Nothing in this module writes. All paths come from `legacy_paths()` which
also locates the repo root. Hash recomputation uses core.hashing helpers —
the same functions the pipeline and pytest use — so the viewer's verdict
matches what `make verify-index` would say.

Caching: every loader is decorated with @st.cache_data so re-opening the
same page doesn't re-read or re-hash files. The cache invalidates when the
underlying mtime changes.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

# Allow `python -m viewer.app` from Ai stock/ dir.
_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import streamlit as st  # noqa: E402

from core.hashing import canonical_sha256  # noqa: E402

REPORTS_DIR = _AI_STOCK / "reports"
SCHEMA_FILE = _AI_STOCK / "schema" / "canonical_schema.json"
INDEX_FILE = REPORTS_DIR / "index.json"
RAW_ARCHIVE_DIR = REPORTS_DIR / "_raw_archive"
DAILY_LOGS_DIR = REPORTS_DIR / "_daily_logs"


# ---------------------------------------------------------------------------
# Cache keys: we key on file mtime+size so cache invalidates on real change
# without needing manual st.cache_data.clear() calls.
# ---------------------------------------------------------------------------

def _file_stamp(p: pathlib.Path) -> tuple[float, int]:
    s = p.stat()
    return (s.st_mtime, s.st_size)


@st.cache_data(show_spinner=False)
def _read_json_cached(path_str: str, _stamp: tuple[float, int]) -> dict[str, Any]:
    """Read JSON keyed by mtime+size. `_stamp` participates in the cache key."""
    return json.loads(pathlib.Path(path_str).read_text(encoding="utf-8"))


def load_index() -> dict[str, Any]:
    """Read reports/index.json."""
    return _read_json_cached(str(INDEX_FILE), _file_stamp(INDEX_FILE))


def load_snapshot(date_key: str) -> dict[str, Any]:
    """Read reports/<date_key>.json (date_key may include .example suffix)."""
    f = REPORTS_DIR / f"{date_key}.json"
    return _read_json_cached(str(f), _file_stamp(f))


def load_schema() -> dict[str, Any]:
    """Read schema/canonical_schema.json."""
    return _read_json_cached(str(SCHEMA_FILE), _file_stamp(SCHEMA_FILE))


# ---------------------------------------------------------------------------
# Integrity recomputation — same functions as `make verify-index`
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def canonical_hash_of_snapshot(date_key: str, _stamp: tuple[float, int]) -> str:
    """Recompute canonical_sha256 of the on-disk snapshot. Cached by mtime."""
    snap = load_snapshot(date_key)
    return canonical_sha256(snap)


def sidecar_hash(date_key: str) -> str | None:
    """Read the recorded hash from <date_key>.json.sha256, or None if missing."""
    sidecar = REPORTS_DIR / f"{date_key}.json.sha256"
    if not sidecar.is_file():
        return None
    return sidecar.read_text(encoding="utf-8").strip().split()[0]


def integrity_status(date_key: str) -> dict[str, Any]:
    """Three-witness check for a single date.

    Returns dict with:
      file_path, exists, sidecar_hash, canonical_hash, index_current_hash,
      sidecar_matches, index_matches, all_three_agree.
    """
    f = REPORTS_DIR / f"{date_key}.json"
    out: dict[str, Any] = {
        "date":       date_key,
        "file_path":  str(f.relative_to(_AI_STOCK)),
        "exists":     f.is_file(),
    }
    if not f.is_file():
        out.update({
            "sidecar_hash":      None,
            "canonical_hash":    None,
            "index_current_hash": None,
            "sidecar_matches":   False,
            "index_matches":     False,
            "all_three_agree":   False,
        })
        return out

    canon = canonical_hash_of_snapshot(date_key, _file_stamp(f))
    side = sidecar_hash(date_key)
    idx = load_index()
    idx_entry = idx.get("snapshots", {}).get(date_key, {})
    idx_hash = idx_entry.get("current_hash")

    out.update({
        "sidecar_hash":       side,
        "canonical_hash":     canon,
        "index_current_hash": idx_hash,
        "sidecar_matches":    side == canon,
        "index_matches":      idx_hash == canon,
        "all_three_agree":    (side == canon) and (idx_hash == canon),
    })
    return out


# ---------------------------------------------------------------------------
# Convenience selectors
# ---------------------------------------------------------------------------

def real_dates() -> list[str]:
    """Sorted list of real ISO date keys in the index (skip *.example)."""
    import datetime as dt
    out: list[str] = []
    for k in load_index().get("snapshots", {}).keys():
        try:
            dt.date.fromisoformat(k)
            out.append(k)
        except ValueError:
            continue
    return sorted(out)


def all_index_keys() -> list[str]:
    """All keys in the index (real + example), sorted."""
    return sorted(load_index().get("snapshots", {}).keys())


def universe_for_date(date_key: str) -> list[str]:
    """Sorted list of tickers in a snapshot."""
    snap = load_snapshot(date_key)
    return sorted(s["ticker"] for s in snap.get("stocks", []))


def all_tickers_across_history() -> list[str]:
    """Union of tickers seen across every real-date snapshot."""
    seen: set[str] = set()
    for d in real_dates():
        seen.update(universe_for_date(d))
    return sorted(seen)


def ticker_history(ticker: str) -> list[dict[str, Any]]:
    """For one ticker, walk dates chronologically and return per-date observation.

    Returns list of dicts, each:
      {date, present, tier, composite_score, change_pct, current_price,
       volume, in_universe, audit_events_for_ticker}
    """
    rows: list[dict[str, Any]] = []
    for d in real_dates():
        snap = load_snapshot(d)
        rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
        events = [
            e for e in snap.get("audit_log", [])
            if e.get("ticker") == ticker
        ]
        rows.append({
            "date":             d,
            "present":          rec is not None,
            "tier":             rec.get("tier") if rec else None,
            "composite_score":  rec.get("composite_score") if rec else None,
            "current_price":    rec.get("current_price") if rec else None,
            "change_pct":       rec.get("change_pct") if rec else None,
            "volume":           rec.get("volume") if rec else None,
            "name":             rec.get("name") if rec else None,
            "in_universe":      rec is not None,
            "audit_events":     events,
        })
    return rows


def daily_log_dates() -> list[str]:
    """Sorted ISO date keys for which a daily log file exists."""
    if not DAILY_LOGS_DIR.is_dir():
        return []
    import datetime as dt
    out: list[str] = []
    for f in sorted(DAILY_LOGS_DIR.glob("*.log")):
        stem = f.stem
        try:
            dt.date.fromisoformat(stem)
            out.append(stem)
        except ValueError:
            continue  # skip launchd.out / launchd.err / etc.
    return out


def load_daily_log(date_key: str) -> list[dict[str, Any]]:
    """Read reports/_daily_logs/<date>.log and return one dict per non-blank line.

    Each line is a JSON record written by tools/daily.py. The file is
    append-only: multiple runs on the same date stack their records in order.
    """
    f = DAILY_LOGS_DIR / f"{date_key}.log"
    if not f.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Tolerate occasional corruption — record a synthetic entry
            out.append({"step": "_parse_error", "raw": line, "status": "fail"})
    return out


def daily_log_runs(date_key: str) -> list[list[dict[str, Any]]]:
    """Group records into runs. A new run starts at every 'orchestrator_start'
    record. Returns list of runs; each run is the full list of its records.
    """
    records = load_daily_log(date_key)
    runs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for r in records:
        if r.get("step") == "orchestrator_start":
            if current:
                runs.append(current)
            current = [r]
        else:
            current.append(r)
    if current:
        runs.append(current)
    return runs


def daily_log_summary_row(date_key: str) -> dict[str, Any]:
    """One-line summary of the most recent run for a given date."""
    runs = daily_log_runs(date_key)
    if not runs:
        return {
            "date":           date_key,
            "run_count":      0,
            "latest_status":  None,
            "latest_started": None,
            "latest_ended":   None,
            "step_count":     0,
        }
    latest = runs[-1]
    started = next((r.get("at") for r in latest if r.get("step") == "orchestrator_start"), None)
    end_rec = next((r for r in latest if r.get("step") == "orchestrator_end"), None)
    return {
        "date":           date_key,
        "run_count":      len(runs),
        "latest_status":  end_rec.get("status") if end_rec else "no_end_record",
        "latest_started": started,
        "latest_ended":   end_rec.get("at") if end_rec else None,
        "step_count":     len(latest),
    }


def archived_raw_paths(date_key: str) -> list[dict[str, Any]]:
    """Return list of {source_id, archived_copy_path, archived_sha256} for one date."""
    snap = load_snapshot(date_key)
    out: list[dict[str, Any]] = []
    for src_id, src in snap.get("provenance", {}).get("sources", {}).items():
        out.append({
            "source_id":          src_id,
            "raw_file":           src.get("raw_file"),
            "raw_sha256":         src.get("raw_sha256"),
            "archived_copy_path": src.get("archived_copy_path"),
            "archived_sha256":    src.get("archived_sha256"),
            "fetched_at":         src.get("fetched_at"),
            "row_count":          src.get("row_count"),
            "provides_fields":    src.get("provides_fields", []),
        })
    return out
