"""Observation-only temporal metrics.

NO scoring. NO ranking. NO trading signals. Only:
  - continuity gaps (which calendar days have no snapshot)
  - per-ticker appearance streaks across dates
  - tier transitions (currently all IGNORE so transitions are mostly null)
  - audit-event counts per snapshot (BOOTSTRAP / LOOKBACK_VERIFIED / WORM / etc.)
  - lookback chain depth distribution

All functions are pure (no side effects) and operate on already-loaded data.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

from viewer.data import (
    all_tickers_across_history,
    load_index,
    load_snapshot,
    real_dates,
    universe_for_date,
)


# ---------------------------------------------------------------------------
# Calendar continuity
# ---------------------------------------------------------------------------

def calendar_gaps(weekends_ok: bool = True) -> list[dict[str, Any]]:
    """Walk consecutive ISO dates between earliest and latest snapshot.

    Returns list of dicts for every gap day:
      {date, is_weekend, reason_hint}
    If weekends_ok=True, Saturdays/Sundays are excluded from the gap list
    (they're expected missing for a TWSE market).
    """
    dates = real_dates()
    if len(dates) < 2:
        return []
    start = dt.date.fromisoformat(dates[0])
    end = dt.date.fromisoformat(dates[-1])
    have = set(dates)
    gaps: list[dict[str, Any]] = []
    d = start
    while d <= end:
        iso = d.isoformat()
        if iso not in have:
            is_we = d.weekday() >= 5
            if weekends_ok and is_we:
                d += dt.timedelta(days=1)
                continue
            gaps.append({
                "date":        iso,
                "is_weekend":  is_we,
                "weekday":     d.strftime("%a"),
                "reason_hint": "weekend"
                              if is_we else "weekday with no snapshot (holiday or missing ingest)",
            })
        d += dt.timedelta(days=1)
    return gaps


def coverage_summary() -> dict[str, Any]:
    dates = real_dates()
    if not dates:
        return {"first_date": None, "last_date": None, "snapshot_count": 0,
                "calendar_span_days": 0, "weekday_gaps": 0}
    start = dt.date.fromisoformat(dates[0])
    end = dt.date.fromisoformat(dates[-1])
    span = (end - start).days + 1
    gaps = calendar_gaps(weekends_ok=True)
    return {
        "first_date":         dates[0],
        "last_date":          dates[-1],
        "snapshot_count":     len(dates),
        "calendar_span_days": span,
        "weekday_gaps":       len(gaps),
    }


# ---------------------------------------------------------------------------
# Per-ticker streaks
# ---------------------------------------------------------------------------

def ticker_appearance_matrix() -> dict[str, list[bool]]:
    """For every ticker ever seen, return [present_on_date_i for i in real_dates()]."""
    dates = real_dates()
    universes = [set(universe_for_date(d)) for d in dates]
    all_t = all_tickers_across_history()
    return {t: [t in u for u in universes] for t in all_t}


def ticker_streaks() -> list[dict[str, Any]]:
    """For each ticker:
       - appearances: total days present
       - current_streak: consecutive days at the tail (counts back from latest)
       - max_streak: longest consecutive run anywhere in the window
       - first_seen, last_seen
    """
    dates = real_dates()
    if not dates:
        return []
    matrix = ticker_appearance_matrix()
    out: list[dict[str, Any]] = []
    for t, row in matrix.items():
        appearances = sum(row)
        # streaks
        max_streak = 0
        cur = 0
        for v in row:
            if v:
                cur += 1
                max_streak = max(max_streak, cur)
            else:
                cur = 0
        # current streak from the tail
        cur_streak = 0
        for v in reversed(row):
            if v:
                cur_streak += 1
            else:
                break
        # first/last seen
        first_idx = next((i for i, v in enumerate(row) if v), None)
        last_idx = next((i for i, v in enumerate(reversed(row)) if v), None)
        first_seen = dates[first_idx] if first_idx is not None else None
        last_seen = dates[-(last_idx + 1)] if last_idx is not None else None
        out.append({
            "ticker":         t,
            "appearances":    appearances,
            "current_streak": cur_streak,
            "max_streak":     max_streak,
            "first_seen":     first_seen,
            "last_seen":      last_seen,
            "coverage_pct":   round(100.0 * appearances / len(dates), 1),
        })
    out.sort(key=lambda r: (-r["appearances"], r["ticker"]))
    return out


# ---------------------------------------------------------------------------
# Tier transitions (placeholder — all IGNORE at P3a)
# ---------------------------------------------------------------------------

def tier_transitions() -> list[dict[str, Any]]:
    """Walk consecutive dates and record ticker tier changes.

    At P3a every tier == IGNORE so this returns an empty list. Wired up so
    the viewer panel works the moment P3b activates scoring.
    """
    dates = real_dates()
    if len(dates) < 2:
        return []
    prev_tiers: dict[str, str] = {}
    transitions: list[dict[str, Any]] = []
    for d in dates:
        snap = load_snapshot(d)
        cur_tiers = {s["ticker"]: s.get("tier") for s in snap.get("stocks", [])}
        for t, new_tier in cur_tiers.items():
            old_tier = prev_tiers.get(t)
            if old_tier is not None and old_tier != new_tier:
                transitions.append({
                    "date":     d,
                    "ticker":   t,
                    "from":     old_tier,
                    "to":       new_tier,
                })
        prev_tiers = cur_tiers
    return transitions


# ---------------------------------------------------------------------------
# Audit / event counts
# ---------------------------------------------------------------------------

def audit_event_counts() -> dict[str, dict[str, int]]:
    """For every real date, counts of audit_log[*].event by name."""
    out: dict[str, dict[str, int]] = {}
    for d in real_dates():
        snap = load_snapshot(d)
        out[d] = dict(Counter(e["event"] for e in snap.get("audit_log", [])))
    return out


def global_event_summary() -> Counter:
    """Total across all dates of every event type."""
    c: Counter = Counter()
    for d in real_dates():
        snap = load_snapshot(d)
        c.update(e["event"] for e in snap.get("audit_log", []))
    return c


# ---------------------------------------------------------------------------
# Lookback chain structure
# ---------------------------------------------------------------------------

def lookback_chain_for(date_key: str) -> dict[str, Any]:
    """Return the lookback chain recorded inside one snapshot.

    Output:
      {
        date: <self>,
        lookback: [
          {date: D, hash: sha256, matches_current: bool, exists_in_index: bool},
          ...
        ],
        window_days: int,
        bootstrap: bool,
      }
    """
    snap = load_snapshot(date_key)
    env = snap.get("environment", {})
    lookback = env.get("lookback_snapshots", {}) or {}
    window = env.get("lookback_window_days", 0)
    idx = load_index().get("snapshots", {})

    entries: list[dict[str, Any]] = []
    for d, h in sorted(lookback.items()):
        idx_entry = idx.get(d)
        cur = idx_entry["current_hash"] if idx_entry else None
        ever = (idx_entry is not None) and any(
            row["hash"] == h for row in idx_entry["history"]
        )
        entries.append({
            "date":             d,
            "hash":             h,
            "matches_current":  cur == h,
            "exists_in_index":  ever,
            "index_current":    cur,
        })

    return {
        "date":          date_key,
        "lookback":      entries,
        "window_days":   window,
        "bootstrap":     len(lookback) == 0,
    }


def lookback_depth_distribution() -> Counter:
    """How many priors does each snapshot have? Counter of depth -> count_of_snapshots."""
    c: Counter = Counter()
    for d in real_dates():
        snap = load_snapshot(d)
        depth = len(snap.get("environment", {}).get("lookback_snapshots", {}) or {})
        c[depth] += 1
    return c


# ---------------------------------------------------------------------------
# Per-snapshot summary used by the Timeline panel
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cross-date audit event aggregation (for the Audit Explorer panel)
# ---------------------------------------------------------------------------

def all_audit_events_flat() -> list[dict[str, Any]]:
    """Walk every real-date snapshot. Return a flat list of audit events with date attached.

    Each row: {date, event, step, ticker, reason, node_path, has_data}
    `has_data` is True if the original record had a non-empty `data` dict
    (useful to flag rows that have extra detail without dumping the entire
    payload into a table).
    """
    out: list[dict[str, Any]] = []
    for d in real_dates():
        snap = load_snapshot(d)
        for e in snap.get("audit_log", []):
            out.append({
                "date":      d,
                "event":     e.get("event"),
                "step":      e.get("step"),
                "ticker":    e.get("ticker"),
                "reason":    e.get("reason") or "",
                "node_path": e.get("node_path"),
                "has_data":  bool(e.get("data")),
            })
    return out


def integrity_summary_all() -> list[dict[str, Any]]:
    """Three-witness integrity for every real date, suitable for a status table.

    Pure projection of viewer.data.integrity_status — duplicated here so
    metrics.py is the one-stop-shop for the app's batch tables.
    """
    from viewer.data import integrity_status
    return [integrity_status(d) for d in real_dates()]


# ---------------------------------------------------------------------------
# Per-snapshot summary used by the Timeline panel
# ---------------------------------------------------------------------------

def snapshot_summary_row(date_key: str) -> dict[str, Any]:
    snap = load_snapshot(date_key)
    env = snap.get("environment", {})
    prov = snap.get("provenance", {})
    audit = snap.get("audit_log", [])
    idx = load_index().get("snapshots", {}).get(date_key, {})
    return {
        "date":                  date_key,
        "universe_size":         snap.get("universe_size", 0),
        "eligible_count":        snap.get("eligible_count", 0),
        "lookback_depth":        len(env.get("lookback_snapshots", {}) or {}),
        "lookback_window_days":  env.get("lookback_window_days"),
        "core_version":          snap.get("core_version"),
        "schema_version":        snap.get("schema_version"),
        "generated_at":          snap.get("generated_at"),
        "current_hash":          idx.get("current_hash"),
        "history_revisions":     len(idx.get("history", [])),
        "audit_event_count":     len(audit),
        "has_worm_violation":    any(e["event"] == "WORM_VIOLATION" for e in audit),
        "has_raw_archived":      any(e["event"] == "RAW_ARCHIVED" for e in audit),
        "source_count":          len(prov.get("sources", {})),
    }
