"""P0.5 state machine reform tests.

Covers the five fixes:
  1. Evidence split — buy-side slowdown → DECELERATING; DISTRIBUTING needs
     sell-side evidence (mfb<0 / W3 / W5)
  2. Debounce — transitions need 2 consecutive snapshots; single-day
     triggers are recorded as events; FAILED/EXITED commit same-day
  3. Veto / lockout — no CONFIRMED within DIST_LOCKOUT_SNAPSHOTS after
     DISTRIBUTING unless streak rebuilt from zero
  4. state_flips_30d + structure_unstable
  5. compute() current state == committed history tail (consistency)
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import state_machine as sm  # noqa: E402


# ----------------------------------------------------------------------
# Snapshot builders
# ----------------------------------------------------------------------

def _stock(ticker="9999", mfb=1000, **kw):
    base = {
        "ticker": ticker, "name": "測試", "main_force_buy": mfb,
        "fii_net_buy": kw.get("fii_net_buy"),
        "broker_count_diff": kw.get("broker_count_diff"),
        "current_price": kw.get("price", 100.0),
        "change_pct": kw.get("change_pct", 0.5),
        "volume": kw.get("volume", 5000),
        "main_force_cost": kw.get("cost", 95.0),
    }
    base.update(kw.get("extra", {}))
    return base


def _snaps(mfb_series, ticker="9999", absent_days=frozenset()):
    """Build snapshots 2026-06-01..N with the given mfb per day.
    absent_days: indices where the ticker is missing from the universe."""
    out = []
    for i, mfb in enumerate(mfb_series):
        date = f"2026-06-{i+1:02d}"
        stocks = []
        if i not in absent_days:
            stocks.append(_stock(ticker=ticker, mfb=mfb))
        # one other ticker so universe/breadth aren't empty
        stocks.append(_stock(ticker="1111", mfb=500))
        out.append({"date": date, "stocks": stocks})
    return out


# ----------------------------------------------------------------------
# Fix 1 — evidence split
# ----------------------------------------------------------------------

def test_buy_slowdown_is_decelerating_not_distributing():
    # Strong run then buy volume shrinks fast (still positive) → velocity
    # turns negative but mfb>0: must be DECELERATING, never DISTRIBUTING.
    series = [5000, 6000, 7000, 6000, 2000, 300, 100]
    ts = sm.compute("9999", _snaps(series))
    assert ts.state != sm.S_DISTRIBUTING
    # raw classifier on the final window must be decelerating
    raw = sm._raw_state_seq("9999", _snaps(series),
                            sm._sector_rank_per_snap(_snaps(series)),
                            [1.0] * len(series), None)
    assert raw[-1][1] == sm.S_DECELERATING


def test_net_sell_is_distributing():
    # Strong run then main force flips to NET SELL on 2 consecutive days
    # (debounce) → DISTRIBUTING commits.
    series = [5000, 6000, 7000, 6000, -3000, -2500]
    ts = sm.compute("9999", _snaps(series))
    assert ts.state in (sm.S_DISTRIBUTING, sm.S_FAILED)  # sell evidence honored
    # and at least one raw window classified DISTRIBUTING
    snaps = _snaps(series)
    raw = sm._raw_state_seq("9999", snaps, sm._sector_rank_per_snap(snaps),
                            [1.0] * len(series), None)
    assert any(s == sm.S_DISTRIBUTING for _, s, _ in raw)


def test_w3_vanish_gives_sell_evidence():
    # streak ≥3 then ticker disappears from latest snapshots (W3)
    series = [5000, 6000, 7000, 8000, 0, 0]
    snaps = _snaps(series, absent_days={4, 5})
    raw = sm._raw_state_seq("9999", snaps, sm._sector_rank_per_snap(snaps),
                            [1.0] * len(series), None)
    # absent 2 snaps (not yet EXITED at 3) — W3 fires → distributing allowed
    assert raw[-1][1] in (sm.S_DISTRIBUTING, sm.S_FAILED)


# ----------------------------------------------------------------------
# Fix 2 — debounce
# ----------------------------------------------------------------------

def test_single_day_blip_does_not_commit():
    raw_seq = [
        ("d1", sm.S_ACCUMULATING, 1),
        ("d2", sm.S_ACCUMULATING, 2),
        ("d3", sm.S_DECELERATING, 2),   # single-day blip
        ("d4", sm.S_ACCUMULATING, 3),
        ("d5", sm.S_ACCUMULATING, 4),
    ]
    committed, events = sm._commit_states(raw_seq)
    assert [s for _, s in committed] == [sm.S_ACCUMULATING] * 5
    assert any(e["type"] == "signal" for e in events)


def test_two_consecutive_days_commit():
    raw_seq = [
        ("d1", sm.S_ACCUMULATING, 1),
        ("d2", sm.S_STRENGTHENING, 3),
        ("d3", sm.S_STRENGTHENING, 4),
    ]
    committed, _ = sm._commit_states(raw_seq)
    assert committed[-1][1] == sm.S_STRENGTHENING
    assert committed[1][1] == sm.S_ACCUMULATING  # not yet committed on day 2


def test_failed_commits_same_day():
    raw_seq = [
        ("d1", sm.S_STRENGTHENING, 3),
        ("d2", sm.S_FAILED, 0),
    ]
    committed, _ = sm._commit_states(raw_seq)
    assert committed[-1][1] == sm.S_FAILED


# ----------------------------------------------------------------------
# Fix 3 — distribution lockout veto
# ----------------------------------------------------------------------

def test_confirmed_vetoed_within_lockout():
    raw_seq = [
        ("d1", sm.S_DISTRIBUTING, 1),
        ("d2", sm.S_DISTRIBUTING, 1),
        ("d3", sm.S_CONFIRMED, 2),   # streak never rebuilt from zero
        ("d4", sm.S_CONFIRMED, 3),
    ]
    committed, events = sm._commit_states(raw_seq)
    assert committed[-1][1] != sm.S_CONFIRMED
    assert any(e["type"] == "veto" for e in events)


def test_confirmed_allowed_after_streak_rebuild():
    # streak collapses to 0 then rebuilds to ≥3 → window re-opened
    raw_seq = [
        ("d1", sm.S_DISTRIBUTING, 1),
        ("d2", sm.S_ACCUMULATING, 0),   # streak hits zero
        ("d3", sm.S_ACCUMULATING, 1),
        ("d4", sm.S_STRENGTHENING, 2),
        ("d5", sm.S_CONFIRMED, 3),       # rebuilt ≥3
        ("d6", sm.S_CONFIRMED, 4),
    ]
    committed, _ = sm._commit_states(raw_seq)
    assert committed[-1][1] == sm.S_CONFIRMED


def test_confirmed_allowed_after_lockout_expires():
    seq = [("d0", sm.S_DISTRIBUTING, 1), ("d0b", sm.S_DISTRIBUTING, 1)]
    # pad past the lockout window with neutral state, streak never zero
    for i in range(sm.DIST_LOCKOUT_SNAPSHOTS + 1):
        seq.append((f"d{i+1}", sm.S_STRENGTHENING, 3))
    seq.append(("dX", sm.S_CONFIRMED, 5))
    seq.append(("dY", sm.S_CONFIRMED, 6))
    committed, _ = sm._commit_states(seq)
    assert committed[-1][1] == sm.S_CONFIRMED


# ----------------------------------------------------------------------
# Fix 4 — flips / structure instability
# ----------------------------------------------------------------------

def test_monotonic_progression_zero_flips():
    committed = [
        ("d1", sm.S_DISCOVERED), ("d2", sm.S_ACCUMULATING),
        ("d3", sm.S_ACCUMULATING), ("d4", sm.S_STRENGTHENING),
        ("d5", sm.S_CONFIRMED),
    ]
    assert sm._flips_30d(committed) == 0


def test_zigzag_counts_flips():
    committed = [
        ("d1", sm.S_ACCUMULATING), ("d2", sm.S_STRENGTHENING),  # up
        ("d3", sm.S_ACCUMULATING),                              # down → flip 1
        ("d4", sm.S_STRENGTHENING),                             # up → flip 2
    ]
    assert sm._flips_30d(committed) == 2


# ----------------------------------------------------------------------
# Fix 5 — consistency + integration smoke
# ----------------------------------------------------------------------

def test_compute_state_equals_history_tail():
    series = [5000, 6000, 7000, 6000, 2000, -300, -100]
    snaps = _snaps(series)
    ts = sm.compute("9999", snaps)
    assert ts.state_history, "history must not be empty"
    assert ts.state == ts.state_history[-1]


def test_run_all_smoke_on_real_snapshots():
    """Integration: run on real reports/ snapshots — no exceptions, and
    every returned state is a known key (incl. the new decelerating)."""
    import json
    reports = sorted((_AI_STOCK / "reports").glob("2026-06-*.json"))
    snaps = []
    for f in reports:
        if f.name.endswith(".intelligence.json") or "example" in f.name:
            continue
        s = json.loads(f.read_text(encoding="utf-8"))
        if s.get("stocks"):
            snaps.append(s)
    if len(snaps) < 3:
        pytest.skip("not enough real snapshots")
    out = sm.run_all(snaps[-8:])
    assert out, "run_all returned empty"
    for ts in out.values():
        assert ts.state in sm.STATE_ORDER
        assert ts.state_flips_30d >= 0
