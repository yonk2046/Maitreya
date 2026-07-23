"""Tests for Wave A2 (交易成本模型 + 資金曲線, docs/migration/EXEC-PLAN-backtest-arc-20260723.md).

Covers:
  2.1 成本模型 — core/paper_trading.py._net_return_pct() 對照手算成本(含 fee_min
      綁定情境);summary["net"] 與頂層(毛)並存,不覆蓋頂層(viewer 相容,見
      .claude/rules/viewer-presentation.md 紅線 + 上面的 A2 派工卡)。
  2.2 權益曲線 + 真 max_drawdown — 修正舊版「max_drawdown 恰等於某單筆報酬」的
      語意錯誤;worst_single_trade 為獨立欄位。
  R2 — BACKTEST_* 參數不進 config_hash(config_snapshot 判斷雜湊)。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import engine_params as ep                       # noqa: E402
from core.paper_trading import (                            # noqa: E402
    _cost_model_dict,
    _equity_curve,
    _net_return_pct,
    run_backtest,
)
from core.strategies import ALL_STRATEGIES, STRATEGY_A, STRATEGY_B  # noqa: E402
from tools.run_backtest import _load_snapshots               # noqa: E402


# ── Fixtures (hand-built, deterministic — same style as test_paper_trading.py) ──

def _rec(t, mf, fii, price, wk="none"):
    return {"ticker": t, "name": t, "main_force_buy": mf, "fii_net_buy": fii,
            "volume": 1000, "change_pct": 0.0, "current_price": price,
            "weakening": {"severity": wk}}


def _snap(date, stocks):
    return {"date": date, "stocks": stocks}


def _two_trade_series():
    """Two independent momentum round trips with very different magnitudes,
    so the sequential-realization equity curve has a real peak/trough that
    cannot coincide with either trade's own return_pct."""
    return [
        _snap("2026-06-01", [_rec("AAA", 10, 5, 100), _rec("BBB", 10, 5, 50)]),
        _snap("2026-06-02", [_rec("AAA", 20, 5, 102), _rec("BBB", 20, 5, 51)]),
        _snap("2026-06-03", [_rec("AAA", 40, 5, 104), _rec("BBB", 40, 5, 52)]),
        _snap("2026-06-04", [_rec("AAA", 80, 5, 106), _rec("BBB", 80, 5, 53)]),  # entries fire
        _snap("2026-06-05", [_rec("AAA", 80, 5, 130), _rec("BBB", 80, 5, 53.2)]),  # fills; AAA peak 130
        _snap("2026-06-08", [_rec("AAA", -1, 5, 118, wk="orange"), _rec("BBB", 80, 5, 53.4)]),  # AAA exits (weakening)
        _snap("2026-06-09", [_rec("AAA", -1, 5, 117), _rec("BBB", -1, 5, 40, wk="red")]),  # AAA fill exit; BBB exits
        _snap("2026-06-10", [_rec("AAA", -1, 5, 116), _rec("BBB", -1, 5, 39)]),  # BBB fill exit
    ]


# ═══════════════════════════════════════════════════════════════════════════
# 2.1 — cost model math
# ═══════════════════════════════════════════════════════════════════════════

def test_net_return_pct_matches_hand_calculated_costs():
    gross, units = 0.05, 1.0
    entry = ep.BACKTEST_POSITION_SIZE * units
    exit_ = entry * (1 + gross)
    buy_fee = max(ep.BACKTEST_FEE_RATE * entry, ep.BACKTEST_FEE_MIN)
    sell_fee = max(ep.BACKTEST_FEE_RATE * exit_, ep.BACKTEST_FEE_MIN)
    tax = ep.BACKTEST_TAX_RATE * exit_
    expected = gross - (buy_fee + sell_fee + tax) / entry
    assert abs(_net_return_pct(gross, units) - expected) < 1e-12


def test_net_return_pct_applies_fee_minimum_for_small_position():
    # Tiny leg: fee_rate * notional < fee_min → fee_min must bind on both legs.
    tiny_units = 20.0 / (ep.BACKTEST_FEE_RATE * ep.BACKTEST_POSITION_SIZE * 10)
    net_zero_gross = _net_return_pct(0.0, tiny_units)
    entry = ep.BACKTEST_POSITION_SIZE * tiny_units
    assert ep.BACKTEST_FEE_RATE * entry < ep.BACKTEST_FEE_MIN   # precondition: fee_min binds
    assert net_zero_gross < 0                                    # pure cost drag on a flat trade
    # round trip cost ≈ 2×fee_min + tax (tax also on entry_notional since gross=0)
    expected = 0.0 - (ep.BACKTEST_FEE_MIN * 2 + ep.BACKTEST_TAX_RATE * entry) / entry
    assert abs(net_zero_gross - expected) < 1e-9


def test_net_return_pct_zero_units_returns_gross_unchanged():
    assert _net_return_pct(0.03, 0.0) == 0.03


def test_top_level_summary_stays_gross_net_is_additive():
    """viewer/cockpit.py 讀 summary 頂層 avg_return/median_return/win_rate/
    sharpe_per_trade 且本輪不動 viewer(紅線)——頂層必須維持毛報酬語意,淨報酬
    只新增在 summary['net'] 底下,不覆蓋頂層鍵。"""
    res = run_backtest(_two_trade_series(), STRATEGY_B)
    assert res.trades, "fixture must produce at least one trade"
    gross_mean = round(sum(t.return_pct for t in res.trades) / len(res.trades), 4)
    assert res.summary["avg_return"] == gross_mean
    assert "net" in res.summary
    assert res.summary["net"]["avg_return"] != res.summary["avg_return"]
    assert res.summary["cost_model"] == _cost_model_dict()


# ═══════════════════════════════════════════════════════════════════════════
# 2.2 — equity curve + real max_drawdown, worst_single_trade independent
# ═══════════════════════════════════════════════════════════════════════════

def test_equity_curve_starts_at_initial_capital():
    res = run_backtest(_two_trade_series(), STRATEGY_B)
    curve = res.summary["equity_curve"]
    assert curve[0] == {"date": None, "equity": round(ep.BACKTEST_INITIAL_CAPITAL, 2), "drawdown": 0.0}
    assert len(curve) == 1 + len(res.trades)   # one point per realized exit


def test_worst_single_trade_independent_from_max_drawdown():
    res = run_backtest(_two_trade_series(), STRATEGY_B)
    assert len(res.trades) >= 2, "fixture must produce ≥2 trades to separate the two stats"
    worst = min(round(t.return_pct, 4) for t in res.trades)
    assert res.summary["worst_single_trade"] == worst
    # the (buggy, pre-fix) behaviour was max_drawdown == worst_single_trade
    assert res.summary["max_drawdown"] != res.summary["worst_single_trade"]


def test_max_drawdown_never_equals_a_single_trade_return_on_real_data():
    """2.2 驗收(全策略回歸,用真實已提交快照):新 max_drawdown 不應等於任何
    單筆報酬——修正舊版語意錯誤(舊版 chip v1 −19.42% 恰等於鴻海單筆、
    mom v1 −2.35% 恰等於台玻單筆)。"""
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots to backtest against")
    checked_any = False
    for strat in ALL_STRATEGIES.values():
        res = run_backtest(snaps, strat)
        mdd = res.summary.get("max_drawdown")
        if mdd is None or not res.trades:
            continue
        checked_any = True
        single_returns = {round(t.return_pct, 4) for t in res.trades}
        assert mdd not in single_returns, (
            f"{strat.name}: max_drawdown {mdd} still equals a single trade's return")
    if not checked_any:
        pytest.skip("no strategy produced trades on the committed snapshots")


# ═══════════════════════════════════════════════════════════════════════════
# R2 — BACKTEST_* must never pollute config_hash
# ═══════════════════════════════════════════════════════════════════════════

def test_backtest_params_excluded_from_config_hash():
    cfg = ep.as_config_dict()
    assert not any(k.startswith("BACKTEST_") for k in cfg), (
        "R2 裁定:回測成本參數不得進 config_snapshot/config_hash")
    # sanity — the constants genuinely exist (not a typo that vacuously passes)
    assert hasattr(ep, "BACKTEST_FEE_RATE")
    assert hasattr(ep, "BACKTEST_FEE_MIN")
    assert hasattr(ep, "BACKTEST_TAX_RATE")
    assert hasattr(ep, "BACKTEST_POSITION_SIZE")
    assert hasattr(ep, "BACKTEST_INITIAL_CAPITAL")


# ═══════════════════════════════════════════════════════════════════════════
# Real-data acceptance checkpoint (清單 2.1 / EXEC-PLAN R2)
# ═══════════════════════════════════════════════════════════════════════════

def test_chip_anchored_swing_net_return_acceptance_checkpoint():
    """驗收:chip_anchored_swing 淨平均應約為 −0.04%(2026-07-23 分析基準)。

    容忍帶 ±0.3pp:這是 2026-07-23 快照集(16 筆交易,2026-05-08→2026-07-23)
    下的已知基準,隨每日 pipeline 累積新交易數字會緩慢漂移——測的是「成本模型
    把毛報酬正確拉進小幅負值區間」,不是鎖死某一天的精確浮點數。
    """
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots to backtest against")
    res = run_backtest(snaps, STRATEGY_A)
    if not res.trades:
        pytest.skip("chip_anchored_swing produced no trades on current snapshots")
    net_avg = res.summary["net"]["avg_return"]
    assert net_avg is not None
    assert abs(net_avg - (-0.0004)) < 0.003, (
        f"chip_anchored_swing net avg_return {net_avg} drifted far from the "
        f"~-0.04% checklist baseline (±0.3pp band)")


def test_determinism_same_snapshots_same_summary():
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots to backtest against")
    r1 = run_backtest(snaps, STRATEGY_A).summary
    r2 = run_backtest(snaps, STRATEGY_A).summary
    assert r1 == r2
