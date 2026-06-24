"""Tests for core/holdings.py (持倉出場警示判斷)."""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.holdings import evaluate_holding, evaluate_holdings  # noqa: E402


def _rec(t, mf=10, fii=10, price=100, wk="none"):
    return {"ticker": t, "name": t, "main_force_buy": mf, "fii_net_buy": fii,
            "current_price": price, "weakening": {"severity": wk}}


def _snaps(seq):  # seq: list of (mf, fii, price, wk) for ticker AAA
    return [{"stocks": [_rec("AAA", *args)]} for args in seq]


def test_pl_and_no_alert_when_healthy():
    snaps = _snaps([(10, 5, 100, "none"), (10, 5, 110, "none")])
    r = evaluate_holding({"ticker": "AAA", "shares": 1000, "cost": 100}, snaps)
    assert r["current_price"] == 110
    assert r["pl_pct"] == 0.10
    assert r["market_value"] == 110000
    assert r["alert"] == "none" and not r["a_exit"] and not r["b_exit"]


def test_weakening_red_lights_red_both():
    snaps = _snaps([(10, 5, 100, "none"), (10, 5, 100, "red")])
    r = evaluate_holding({"ticker": "AAA", "cost": 100}, snaps)
    assert r["alert"] == "red"
    assert r["a_exit"] and r["b_exit"]
    assert any("轉弱red" in x for x in r["a_reasons"])


def test_main_force_two_day_sell_is_A_red():
    snaps = _snaps([(10, 5, 100, "none"), (-5, 5, 100, "none"), (-3, 5, 100, "none")])
    r = evaluate_holding({"ticker": "AAA", "cost": 100}, snaps)
    assert r["a_exit"] and "主力連2日淨賣" in r["a_reasons"]
    assert r["alert"] == "red"


def test_fii_two_day_reversal_is_B_red():
    snaps = _snaps([(10, 5, 100, "none"), (10, -2, 100, "none"), (10, -4, 100, "none")])
    r = evaluate_holding({"ticker": "AAA", "cost": 100}, snaps)
    assert r["b_exit"] and "外資連2日反向" in r["b_reasons"]
    assert r["alert"] == "red"


def test_trailing_retrace_is_orange():
    # peak 120 then -10% to 108 → ≥8% retrace, soft → orange (no hard signal)
    snaps = _snaps([(10, 5, 100, "none"), (10, 5, 120, "none"), (10, 5, 108, "none")])
    r = evaluate_holding({"ticker": "AAA", "cost": 100}, snaps)
    assert r["b_exit"] and any("回落" in x for x in r["b_reasons"])
    assert r["alert"] == "orange"


def test_sort_alerts_to_top():
    snaps_red = _snaps([(10, 5, 100, "none"), (10, 5, 100, "red")])
    snaps_ok = _snaps([(10, 5, 100, "none"), (10, 5, 100, "none")])
    # merge two tickers into one snapshot chain
    chain = [{"stocks": [a["stocks"][0], {**b["stocks"][0], "ticker": "BBB"}]}
             for a, b in zip(snaps_red, snaps_ok)]
    out = evaluate_holdings([{"ticker": "BBB", "cost": 100}, {"ticker": "AAA", "cost": 100}], chain)
    assert out[0]["ticker"] == "AAA" and out[0]["alert"] == "red"   # alert first
