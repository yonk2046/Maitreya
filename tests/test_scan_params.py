"""Test the parameter-sweep helper (deterministic; uses crafted snapshots)."""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.strategies import STRATEGY_B          # noqa: E402
from tools.scan_params import scan                # noqa: E402


def _rec(t, mf, fii, price):
    return {"ticker": t, "name": t, "main_force_buy": mf, "fii_net_buy": fii,
            "volume": 1000, "change_pct": 0.0, "current_price": price,
            "weakening": {"severity": "none"}}


def _series():
    return [
        {"date": "2026-06-01", "stocks": [_rec("AAA", 10, 5, 100)]},
        {"date": "2026-06-02", "stocks": [_rec("AAA", 20, 5, 102)]},
        {"date": "2026-06-03", "stocks": [_rec("AAA", 40, 5, 104)]},
        {"date": "2026-06-04", "stocks": [_rec("AAA", 80, 5, 106)]},
        {"date": "2026-06-05", "stocks": [_rec("AAA", 90, 5, 110)]},
    ]


def test_scan_shape_and_determinism():
    snaps = _series()
    out = scan(snaps, STRATEGY_B, "entry_streak_min", [3, 4, 5])
    assert out["param"] == "entry_streak_min"
    assert [r["value"] for r in out["rows"]] == [3, 4, 5]
    assert all("win_rate" in r and "trades" in r for r in out["rows"])
    assert scan(snaps, STRATEGY_B, "entry_streak_min", [3, 4, 5]) == out  # deterministic


def test_higher_streak_is_not_more_trades():
    # a stricter entry threshold can only reduce (never increase) entries
    snaps = _series()
    out = scan(snaps, STRATEGY_B, "entry_streak_min", [3, 5])
    t3 = out["rows"][0]["trades"]
    t5 = out["rows"][1]["trades"]
    assert t5 <= t3
