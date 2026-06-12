"""P0.6 — dual-anchor main-force cost tests (雙錨主力成本).

cost_recent (newest batch) vs cost_episode_weighted (volume-weighted real
entry base over the trailing buy episode). Divergence > 5% → ⚠ 成本背離;
gate consumers use cost_conservative = min(both).
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.market_context import dual_cost_anchor  # noqa: E402


def _snaps(rows, ticker="9999"):
    """rows: list of (cost, mfb) or None for absent day."""
    out = []
    for i, row in enumerate(rows):
        stocks = []
        if row is not None:
            cost, mfb = row
            stocks.append({"ticker": ticker, "main_force_cost": cost,
                           "main_force_buy": mfb})
        out.append({"date": f"2026-06-{i+1:02d}", "stocks": stocks})
    return out


def test_rally_divergence_detected():
    # Rising rally: episode base 100→120, recent batch at 120.
    # Episode-weighted ≈ (100·1000 + 110·1000 + 120·1000)/3000 = 110
    # Recent 120 vs 110 → +9.09% divergence > 5% → flagged
    a = dual_cost_anchor("9999", _snaps([(100, 1000), (110, 1000), (120, 1000)]))
    assert a["cost_recent"] == 120
    assert a["cost_episode_weighted"] == 110.0
    assert a["cost_conservative"] == 110.0          # conservative = lower anchor
    assert a["divergence_pct"] == 9.09
    assert a["diverged"] is True
    assert a["episode_len"] == 3


def test_flat_cost_no_divergence():
    a = dual_cost_anchor("9999", _snaps([(100, 500), (101, 500), (100, 500)]))
    assert a["diverged"] is False
    assert abs(a["divergence_pct"]) < 5


def test_episode_breaks_on_sell_day():
    # Sell day (mfb<0) breaks the episode: only the last 2 buy days count
    a = dual_cost_anchor("9999", _snaps([(80, 9000), (90, -100), (110, 1000), (120, 1000)]))
    assert a["episode_len"] == 2
    assert a["cost_episode_weighted"] == 115.0      # 80@9000 excluded
    assert a["cost_recent"] == 120


def test_episode_breaks_on_absence():
    a = dual_cost_anchor("9999", _snaps([(80, 9000), None, (110, 1000), (120, 1000)]))
    assert a["episode_len"] == 2
    assert a["cost_episode_weighted"] == 115.0


def test_volume_weighting_matters():
    # Heavy buying at 100, light topping at 130:
    # weighted = (100·9000 + 130·1000)/10000 = 103 — far from recent 130
    a = dual_cost_anchor("9999", _snaps([(100, 9000), (130, 1000)]))
    assert a["cost_episode_weighted"] == 103.0
    assert a["cost_conservative"] == 103.0
    assert a["diverged"] is True                    # 130 vs 103 = +26%


def test_missing_cost_days_excluded_from_weighting():
    a = dual_cost_anchor("9999", _snaps([(100, 1000), (None, 1000), (110, 1000)]))
    assert a["episode_len"] == 3                    # day stays in episode
    assert a["cost_episode_weighted"] == 105.0      # but excluded from weights


def test_no_data_graceful():
    a = dual_cost_anchor("9999", _snaps([(None, 1000)]))
    assert a["cost_recent"] is None
    assert a["cost_episode_weighted"] is None
    assert a["cost_conservative"] is None
    assert a["diverged"] is False
    a2 = dual_cost_anchor("9999", [])
    assert a2["cost_recent"] is None


def test_no_episode_when_latest_is_sell():
    a = dual_cost_anchor("9999", _snaps([(100, 1000), (105, -500)]))
    assert a["episode_len"] == 0
    assert a["cost_episode_weighted"] is None
    assert a["cost_recent"] == 105                  # recent anchor still reported
    assert a["cost_conservative"] == 105


def test_golden_entries_carry_anchor_fields():
    """Integration: golden.run on real snapshots exposes the new fields."""
    import json
    from core import golden
    reports = sorted((_AI_STOCK / "reports").glob("2026-06-*.json"))
    snaps = []
    for f in reports:
        if f.name.endswith(".intelligence.json") or "example" in f.name:
            continue
        s = json.loads(f.read_text(encoding="utf-8"))
        if s.get("stocks"):
            snaps.append(s)
    if len(snaps) < 3:
        import pytest
        pytest.skip("not enough real snapshots")
    gr = golden.run(snaps)
    entries = gr.prime + gr.strong + gr.qualified + gr.near_miss
    assert entries
    e = entries[0].as_dict()
    for k in ("cost_episode_weighted", "cost_conservative",
              "cost_divergence_pct", "cost_diverged"):
        assert k in e
