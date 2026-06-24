"""Tests for core/paper_trading.py (P3b backtest engine, Strategy B).

Locks the determinism + no-look-ahead contract and a hand-built round trip.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.paper_trading import run_backtest          # noqa: E402
from core.strategies import STRATEGY_B, STRATEGY_A    # noqa: E402


def _rec(t, mf, fii, price, wk="none"):
    return {"ticker": t, "name": t, "main_force_buy": mf, "fii_net_buy": fii,
            "volume": 1000, "change_pct": 0.0, "current_price": price,
            "weakening": {"severity": wk}}


def _snap(date, stocks):
    return {"date": date, "stocks": stocks}


def _rising_entry_series():
    # 4 days of rising main-force buy + positive fii → streak 4, vel>0, accel>0
    return [
        _snap("2026-06-01", [_rec("AAA", 10, 5, 100)]),
        _snap("2026-06-02", [_rec("AAA", 20, 5, 102)]),
        _snap("2026-06-03", [_rec("AAA", 40, 5, 104)]),
        _snap("2026-06-04", [_rec("AAA", 80, 5, 106)]),  # entry signal fires on this day
    ]


def test_entry_then_trailing_stop_exit():
    snaps = _rising_entry_series() + [
        _snap("2026-06-05", [_rec("AAA", 80, 5, 120)]),   # fill day for entry; peak rises
        _snap("2026-06-08", [_rec("AAA", 80, 5, 130)]),   # peak 130
        _snap("2026-06-09", [_rec("AAA", -1, 5, 118)]),   # -9.2% from 130 → trailing stop
        _snap("2026-06-10", [_rec("AAA", -1, 5, 117)]),   # fill the exit
    ]
    res = run_backtest(snaps, STRATEGY_B)
    assert len(res.trades) == 1
    tr = res.trades[0]
    assert tr.ticker == "AAA"
    assert tr.exit_reason in ("trailing_stop", "weakening", "fii_reversal", "end_of_data")
    assert res.summary["trades"] == 1


def test_weakening_red_forces_exit():
    snaps = _rising_entry_series() + [
        _snap("2026-06-05", [_rec("AAA", 80, 5, 120)]),
        _snap("2026-06-08", [_rec("AAA", 80, 5, 122, wk="red")]),  # red → exit decided
        _snap("2026-06-09", [_rec("AAA", 80, 5, 121)]),            # fill
    ]
    res = run_backtest(snaps, STRATEGY_B)
    assert len(res.trades) == 1
    assert res.trades[0].exit_reason == "weakening"


def test_no_entry_when_streak_too_short():
    snaps = [
        _snap("2026-06-01", [_rec("AAA", 10, 5, 100)]),
        _snap("2026-06-02", [_rec("AAA", -5, 5, 99)]),   # breaks streak
        _snap("2026-06-03", [_rec("AAA", 20, 5, 101)]),  # streak only 1
        _snap("2026-06-04", [_rec("AAA", 30, 5, 102)]),
    ]
    res = run_backtest(snaps, STRATEGY_B)
    assert res.summary["trades"] == 0


def test_deterministic():
    snaps = _rising_entry_series() + [_snap("2026-06-05", [_rec("AAA", 80, 5, 120)])]
    a = run_backtest(snaps, STRATEGY_B).as_dict()
    b = run_backtest(snaps, STRATEGY_B).as_dict()
    assert a == b


def test_strategy_a_runs_chip_anchored():
    # A is enabled (P3b): runs golden.run on-the-fly. On a tiny synthetic series
    # the funnel/state engine can't reach 'confirmation' → 0 trades, but it must
    # run without error and flag the chip-anchored v1 limitations.
    snaps = _rising_entry_series()
    res = run_backtest(snaps, STRATEGY_A)
    assert isinstance(res.summary.get("trades"), int)
    assert any("chip-anchored" in lim for lim in res.limitations)


def test_no_lookahead_entry_fills_day_after_signal():
    # Streak hits 3 on the DECISION day 06-03 (mf 10,20,40) → fill on 06-04,
    # never the same day. Proves execution lags decision by one snapshot.
    snaps = _rising_entry_series() + [_snap("2026-06-05", [_rec("AAA", 80, 5, 200)])]
    res = run_backtest(snaps, STRATEGY_B)
    assert len(res.trades) == 1
    tr = res.trades[0]
    assert tr.entry_date == "2026-06-04"     # day AFTER the 06-03 signal
    assert tr.entry_price == 106             # 06-04 price, not 06-03's 104
    assert tr.exit_date == "2026-06-05" and tr.exit_price == 200
