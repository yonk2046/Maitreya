"""Tests for the golden-list strategy tagging (CHECKLIST Part 1, §1.4).

Three acceptance gates:
  (1) 一致性 — the tags produced by strategy_tags_for_date match the backtest
      engine's entry decisions on the same slice (both go through the single
      source of truth core.strategies.would_enter). This is the regression net
      against 標示/回測 drift (governance redline 5).
  (2) 決定論 — same slice twice → byte-identical tags.
  (3) 治理 — tagging never mutates the snapshot and never emits
      tier/composite_score/gates (those stay 100% owned by core.golden).
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.paper_trading import run_backtest                       # noqa: E402
from core.strategies import (                                     # noqa: E402
    STRATEGY_A, STRATEGY_B, strategy_tags_for_date, would_enter,
)


def _rec(t, mf, fii, price, wk="none"):
    return {"ticker": t, "name": t, "main_force_buy": mf, "fii_net_buy": fii,
            "volume": 1000, "change_pct": 0.0, "current_price": price,
            "weakening": {"severity": wk}}


def _snap(date, stocks):
    return {"date": date, "stocks": stocks}


def _series():
    # AAA: rising main-force + positive fii → qualifies for momentum (B) on 06-04.
    # BBB: broken streak → never qualifies.
    return [
        _snap("2026-06-01", [_rec("AAA", 10, 5, 100), _rec("BBB", 10, 5, 50)]),
        _snap("2026-06-02", [_rec("AAA", 20, 5, 102), _rec("BBB", -5, 5, 49)]),
        _snap("2026-06-03", [_rec("AAA", 40, 5, 104), _rec("BBB", 20, 5, 51)]),
        _snap("2026-06-04", [_rec("AAA", 80, 5, 106), _rec("BBB", 30, 5, 52)]),
        _snap("2026-06-05", [_rec("AAA", 80, 5, 120), _rec("BBB", 40, 5, 53)]),
    ]


# ── (1) 一致性 ──────────────────────────────────────────────────────────────
def test_tags_equal_would_enter_on_same_slice():
    """對固定切片,strategy_tags_for_date 標示的集合 == would_enter 判定的集合。

    這證明標示函數忠實反映共用進場閘門 would_enter,不是另一份平行邏輯。
    """
    snaps = _series()
    strategies = {"A": STRATEGY_A, "B": STRATEGY_B}
    for k in range(2, len(snaps) + 1):
        sl = snaps[:k]
        tags = strategy_tags_for_date(sl, strategies)
        for label, cfg in strategies.items():
            tagged = {t for t, v in tags.items() if label in v["tags"]}
            gate = {rec["ticker"]
                    for rec in sl[-1].get("stocks", [])
                    if would_enter(rec["ticker"], sl, cfg)[0]}
            assert tagged == gate, f"slice[:{k}] strategy {label}: {tagged} != {gate}"


def test_every_backtest_entry_was_tagged_on_its_decision_day():
    """回測引擎在某日對策略 B 的每一筆進場,在該決策日的 strategy_tags 必含 B。

    這把『實際回測進場』與『UI 標示』綁在一起:引擎進的,標示一定標了。
    """
    snaps = _series()
    dates = [s["date"] for s in snaps]
    res = run_backtest(snaps, STRATEGY_B)
    assert res.trades, "fixture should produce at least one B entry"
    for tr in res.trades:
        # fill happens on entry_date (day i+1); the decision was day i.
        fill_i = dates.index(tr.entry_date)
        decision_slice = snaps[:fill_i]          # snaps[:i+1], decision day = i
        assert would_enter(tr.ticker, decision_slice, STRATEGY_B)[0], \
            f"{tr.ticker} entered {tr.entry_date} but would_enter=False on decision day"
        tags = strategy_tags_for_date(decision_slice, {"B": STRATEGY_B})
        assert "B" in tags.get(tr.ticker, {}).get("tags", []), \
            f"{tr.ticker} entered {tr.entry_date} but was not tagged B on decision day"


def test_rejections_present_for_untagged_strategy():
    """被標示的標的,對未取得的策略要附未通過原因(供 tooltip)。"""
    # decision day 06-04 (snaps[:4]) is where AAA's momentum fires for B.
    snaps = _series()[:4]
    tags = strategy_tags_for_date(snaps, {"A": STRATEGY_A, "B": STRATEGY_B})
    assert "AAA" in tags and "B" in tags["AAA"]["tags"]
    # AAA momentum passes but chip-anchored (A) does not on this synthetic slice
    assert "A" in tags["AAA"]["rejections"]
    assert tags["AAA"]["rejections"]["A"]      # non-empty reason list


# ── (2) 決定論 ──────────────────────────────────────────────────────────────
def test_tags_deterministic_byte_identical():
    snaps = _series()
    strategies = {"A": STRATEGY_A, "B": STRATEGY_B}
    a = strategy_tags_for_date(snaps, strategies)
    b = strategy_tags_for_date(snaps, strategies)
    assert a == b
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == \
        json.dumps(b, sort_keys=True, ensure_ascii=False)


# ── (3) 治理 ────────────────────────────────────────────────────────────────
def test_tagging_does_not_mutate_snapshots():
    snaps = _series()
    before = json.dumps(snaps, sort_keys=True, ensure_ascii=False)
    strategy_tags_for_date(snaps, {"A": STRATEGY_A, "B": STRATEGY_B})
    after = json.dumps(snaps, sort_keys=True, ensure_ascii=False)
    assert before == after, "strategy_tags_for_date must not mutate input snapshots"


def test_tags_output_carries_no_scoring_fields():
    """標示輸出不得帶 tier / composite_score / gates / rankings(那是 core.golden 專屬)。"""
    snaps = _series()
    tags = strategy_tags_for_date(snaps, {"A": STRATEGY_A, "B": STRATEGY_B})
    blob = json.dumps(tags, ensure_ascii=False)
    for forbidden in ("tier", "composite_score", "gates", "rankings"):
        assert forbidden not in blob, f"tags leaked scoring field {forbidden!r}"


def test_golden_scoring_unchanged_by_tagging():
    """治理:計算標示前後,同一切片的 golden tier/score/gates 完全未變。"""
    from core import golden as _golden
    snaps = _series()
    g_before = _golden.run(snaps).as_dict()
    strategy_tags_for_date(snaps, {"A": STRATEGY_A, "B": STRATEGY_B})
    g_after = _golden.run(snaps).as_dict()
    assert g_before == g_after
