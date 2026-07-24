"""Wave C1 — 策略 v3(交換鬆緊 + 三重止損)驗收(研究待審,非上線)。

規範:MAITREYA_CHECKLIST_20260723.md Part 4.3 + docs/migration/EXEC-PLAN-backtest-arc-20260723.md（C1 卡 / R2）。

鎖定:
  4.3 進場層2 動能否決權:velocity_3d>0 且 acceleration>=0 且 外資同向 且 轉弱 none
  4.3 進場層3 成本位階分流:放寬成本閘門至 COST_CAP(1.15);≤FULL_TIER(1.05)→1.0 單位,其上→0.5
  4.3 三重止損:S1 硬熔斷 / S2 進場價止損 / S3 結構低點(取最先觸發,S1/S2 不依賴籌碼旗標)
  4.3 TP1/加碼/減碼移除(單筆進出)
  紅線:進場判斷唯一來源=would_enter(v3 也走它);參數全在 engine_params BACKTEST_*(R2,不入 config_hash)

byte-identical 回歸(A/B/v2 既有交易不得被 v3 改動)由 CI/人工比對核對(hash),此檔另鎖
「四策略未開啟 v3 旗標」的結構不變量以佐證 v3 走獨立碼路。
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import engine_params as ep                              # noqa: E402
from core.hashing import canonical_sha256                        # noqa: E402
from core.paper_trading import run_backtest                      # noqa: E402
from core.strategies import (                                    # noqa: E402
    ALL_STRATEGIES, STRATEGY_A, STRATEGY_A_V2, STRATEGY_A_V3,
    STRATEGY_B, STRATEGY_B_V2, would_enter,
)
from tools.run_backtest import _load_snapshots                   # noqa: E402

_V3_EXIT_REASONS = {"weakening", "hard_break", "entry_stop",
                    "atr_stop", "trailing_stop", "end_of_data"}
# v2 分批機制的出場理由 — v3 移除後不得再出現
_V2_ONLY_REASONS = {"tp1", "vel_reduce", "main_force_sell", "W3_hardstop", "weakening_tp2"}


# ── fixtures ────────────────────────────────────────────────────────────────

def _golden_with(ticker: str, cost: float):
    """最小 golden_result 替身:only .prime/.strong 與 entry.ticker/cost_* 被 would_enter 讀。"""
    e = SimpleNamespace(ticker=ticker, cost_conservative=cost, main_force_cost=cost)
    return SimpleNamespace(prime=[e], strong=[])


def _chain(mf_seq, price, fii, wk="none", ticker="TSTV"):
    """單標的快照鏈:mf_seq 建立主力買超趨勢(定 velocity/accel);末日帶 price/fii/weakening。"""
    snaps = []
    last = len(mf_seq) - 1
    for k, mf in enumerate(mf_seq):
        is_last = k == last
        rec = {"ticker": ticker, "name": ticker, "main_force_buy": mf,
               "fii_net_buy": fii if is_last else 100,
               "current_price": price if is_last else 50.0, "volume": 1000,
               "weakening": {"severity": wk if is_last else "none"}}
        snaps.append({"date": f"2026-06-{k + 1:02d}", "stocks": [rec]})
    return snaps


# ── R2:參數在 engine_params BACKTEST_*,不入 config_hash ─────────────────────

def test_v3_params_exist_sane_and_excluded_from_hash():
    for name, lo, hi in [("BACKTEST_COST_FULL_TIER", 1.0, 1.10),
                         ("BACKTEST_COST_CAP", 1.10, 1.30),
                         ("BACKTEST_COST_BREAK", 0.85, 1.0),
                         ("BACKTEST_ENTRY_STOP", 0.85, 1.0)]:
        assert hasattr(ep, name), f"缺參數 {name}"
        assert lo <= getattr(ep, name) <= hi, f"{name} 超出合理範圍"
    assert ep.BACKTEST_COST_FULL_TIER < ep.BACKTEST_COST_CAP     # 全倉分界 < 進場上界
    cfg = ep.as_config_dict()
    assert not any(k.startswith("BACKTEST_") for k in cfg)       # R2:BACKTEST_* 全部排除


# ── 註冊 + 結構不變量 ────────────────────────────────────────────────────────

def test_v3_registered():
    assert "chip_anchored_v3" in ALL_STRATEGIES
    v3 = ALL_STRATEGIES["chip_anchored_v3"]
    assert v3 is STRATEGY_A_V3
    assert v3.kind == "chip_anchored" and v3.enabled
    assert v3.momentum_veto is True and v3.triple_stop is True


def test_existing_four_do_not_enable_v3_flags():
    """佐證 byte-identical:既有四策略不開 v3 旗標 → 永不進 would_enter v3 分支/v3 引擎。"""
    for s in (STRATEGY_A, STRATEGY_A_V2, STRATEGY_B, STRATEGY_B_V2):
        assert s.momentum_veto is False and s.triple_stop is False


# ── 4.3 進場層2 動能否決權(would_enter,唯一進場來源)────────────────────────

def test_v3_entry_passes_when_all_conditions_met():
    snaps = _chain([10, 30, 60, 100], price=102, fii=500, wk="none")   # ratio 1.02
    ok, reasons = would_enter("TSTV", snaps, STRATEGY_A_V3, golden_result=_golden_with("TSTV", 100))
    assert ok and reasons == []


def test_v3_veto_velocity_not_positive():
    snaps = _chain([100, 60, 30], price=102, fii=500, wk="none")       # velocity < 0
    ok, reasons = would_enter("TSTV", snaps, STRATEGY_A_V3, golden_result=_golden_with("TSTV", 100))
    assert not ok and any("速度" in r for r in reasons)


def test_v3_veto_acceleration_negative():
    snaps = _chain([10, 50, 80, 100], price=102, fii=500, wk="none")   # velocity>0 但 accel<0
    ok, reasons = would_enter("TSTV", snaps, STRATEGY_A_V3, golden_result=_golden_with("TSTV", 100))
    assert not ok and any("加速度" in r for r in reasons)


def test_v3_veto_fii_not_aligned():
    snaps = _chain([10, 30, 60, 100], price=102, fii=-200, wk="none")
    ok, reasons = would_enter("TSTV", snaps, STRATEGY_A_V3, golden_result=_golden_with("TSTV", 100))
    assert not ok and any("外資" in r for r in reasons)


def test_v3_veto_weakening_not_none():
    snaps = _chain([10, 30, 60, 100], price=102, fii=500, wk="orange")
    ok, reasons = would_enter("TSTV", snaps, STRATEGY_A_V3, golden_result=_golden_with("TSTV", 100))
    assert not ok and any("轉弱" in r for r in reasons)


# ── 4.3 進場層3 成本位階分流(放寬閘門 / 上界)────────────────────────────────

def test_v3_relaxes_cost_gate_between_full_tier_and_cap():
    """v3 收 1.05<價/本≤1.15;A(緊閘 1.05)拒同一筆 → 證明「放寬成本閘門」且 A 未被鬆動。"""
    snaps = _chain([10, 30, 60, 100], price=110, fii=500, wk="none")   # ratio 1.10
    g = _golden_with("TSTV", 100)
    ok_v3, _ = would_enter("TSTV", snaps, STRATEGY_A_V3, golden_result=g)
    ok_a, reasons_a = would_enter("TSTV", snaps, STRATEGY_A, golden_result=g)
    assert ok_v3 is True
    assert ok_a is False and reasons_a == ["價/本 1.10 超出上限 1.05"]   # A byte-identical 拒單字串


def test_v3_rejects_above_cost_cap():
    snaps = _chain([10, 30, 60, 100], price=120, fii=500, wk="none")   # ratio 1.20 > 1.15
    ok, reasons = would_enter("TSTV", snaps, STRATEGY_A_V3, golden_result=_golden_with("TSTV", 100))
    assert not ok and reasons == ["價/本 1.20 超出上限 1.15"]


# ── v3 引擎不變量(真實快照)──────────────────────────────────────────────────

def test_v3_engine_invariants_on_real_data():
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots")
    res = run_backtest(snaps, STRATEGY_A_V3)
    reasons = {t.exit_reason for t in res.trades}
    assert reasons <= _V3_EXIT_REASONS, f"未預期出場理由:{reasons - _V3_EXIT_REASONS}"
    assert not (reasons & _V2_ONLY_REASONS), "v3 不得出現 TP1/加碼/減碼/W3 分批出場理由"
    for t in res.trades:
        assert t.units in (0.5, 1.0), f"{t.ticker} 位階分流單位異常 {t.units}"       # 4.3 進場層3
        if t.exit_reason == "atr_stop":
            assert t.return_pct < 0, f"{t.ticker} atr_stop 出場報酬 {t.return_pct} ≥ 0"  # 3.1


def test_v3_deterministic_on_real_data():
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots")
    h1 = canonical_sha256(run_backtest(snaps, STRATEGY_A_V3).as_dict())
    h2 = canonical_sha256(run_backtest(snaps, STRATEGY_A_V3).as_dict())
    assert h1 == h2
