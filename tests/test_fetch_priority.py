"""Tests for the branch-fetch priority list (fetch_daily Step 7).

The daily Sinotrade branch fetch is capped (~40 tickers). These tests lock the
contract that the names we actually track — 記憶體 anchors, Tier-A anchors,
prior-day golden, and high cumulative-net-buy — always survive the cap, and that
the prior-snapshot seed reads safely.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools.fetch_daily import (  # noqa: E402
    MEMORY_ANCHORS,
    build_branch_fetch_list,
    _prior_priority_from_snapshot,
)

TIER_A = ["2330", "2317", "2382", "2454", "2308", "2881", "2882", "2891"]


def _kw(**over):
    base = dict(
        memory=MEMORY_ANCHORS, tier_a=TIER_A,
        prior_golden=[], prior_high_net=[],
        cross=[], fii_top=[], mf_top=[], fii_sell_top=[], mf_sell_top=[],
        cap=40,
    )
    base.update(over)
    return base


def test_priority_order_memory_first():
    out = build_branch_fetch_list(**_kw(prior_high_net=["9999"], cross=["1111"]))
    assert out[:3] == MEMORY_ANCHORS           # 記憶體 anchors lead
    assert out[3:11] == TIER_A                  # then Tier-A
    assert "9999" in out and "1111" in out


def test_dedup_preserves_first_position():
    # a ticker appearing in both memory and today's榜 keeps its early slot once
    out = build_branch_fetch_list(**_kw(mf_top=["2344", "5555"]))
    assert out.count("2344") == 1
    assert out.index("2344") < out.index("5555")


def test_anchors_survive_the_cap():
    # flood today's rankings with 50 names; anchors must still make the 40-cap
    flood = [f"{9000 + i}" for i in range(50)]
    out = build_branch_fetch_list(**_kw(cross=flood, cap=40))
    assert len(out) == 40
    for t in MEMORY_ANCHORS + TIER_A:
        assert t in out, f"{t} dropped by cap"


def test_high_net_priority_beats_today_rankings():
    out = build_branch_fetch_list(**_kw(prior_high_net=["7777"], cross=["8888"]))
    assert out.index("7777") < out.index("8888")


def test_prior_snapshot_seed_real_data():
    golden, high_net = _prior_priority_from_snapshot(str(_AI_STOCK / "reports"))
    assert isinstance(golden, list) and isinstance(high_net, list)
    assert len(high_net) > 0          # 6/22 snapshot has net_cumulative flow
    assert all(isinstance(t, str) for t in high_net)


def test_missing_reports_dir_is_safe():
    assert _prior_priority_from_snapshot("/no/such/dir") == ([], [])
