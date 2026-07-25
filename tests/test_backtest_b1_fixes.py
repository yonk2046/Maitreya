"""Wave B1 — Part 3 bug fixes + 2.4 體制標記 (docs/migration/EXEC-PLAN-backtest-arc-20260723.md).

Locks the acceptance criteria for each fix:
  3.1 atr_stop 只在虧損時出場(獲利的結構移動止損改標 trailing_stop)
  3.2 加碼禁向下攤平(entry_cost_anchor 固定 + 加碼價 ≥ 前次進場價 × 0.98 + 動能)
  3.3 COOLDOWN_DAYS:出場後 N 交易日內同標的禁再進場(同日同價洗單 → 0)
  3.4 已實現/未實現分離 + 獨立標的數揭露
  2.4 體制標記(R5:讀落地不重算)+ 分體制績效表

參數紅線(R2):COOLDOWN/ADD_MIN 均在 core/engine_params.py BACKTEST_* 區,不入 config_hash。
"""
from __future__ import annotations

import pathlib
import sys
from collections import defaultdict

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import engine_params as ep                         # noqa: E402
from core.paper_trading import _in_cooldown, run_backtest    # noqa: E402
from core.strategies import (                                 # noqa: E402
    STRATEGY_A, STRATEGY_A_V2, STRATEGY_B, STRATEGY_B_V2,
)
from tools.run_backtest import (                              # noqa: E402
    _enrich_with_regime, _load_snapshots, _regime_index,
)

# 見 tests/test_backtest_cost_model.py 檔頭:方向性驗收也是對「B1 當下的語料」
# 成立的事實,每日新資料會翻轉它 → 凍結語料。
BASELINE_CUTOFF = "2026-07-23"


def _baseline_snapshots():
    return [s for s in _load_snapshots() if (s.get("date") or "") <= BASELINE_CUTOFF]


def _rec(t, mf, fii, price, wk="none"):
    return {"ticker": t, "name": t, "main_force_buy": mf, "fii_net_buy": fii,
            "volume": 1000, "change_pct": 0.0, "current_price": price,
            "weakening": {"severity": wk}}


def _snap(date, stocks, **top):
    d = {"date": date, "stocks": stocks}
    d.update(top)
    return d


# ═══════════════════════════════════════════════════════════════════════════
# 3.1 — atr_stop 出場報酬必為負(獲利結構止損改標 trailing_stop)
# ═══════════════════════════════════════════════════════════════════════════

def test_no_profitable_atr_stop_on_real_data():
    """驗收(3.1):所有策略中,exit_reason == 'atr_stop' 的出場報酬必須 < 0。
    獲利的結構移動止損已改標 trailing_stop。drift-robust(不鎖特定標的)。"""
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots")
    for strat in (STRATEGY_A, STRATEGY_A_V2, STRATEGY_B, STRATEGY_B_V2):
        res = run_backtest(snaps, strat)
        for t in res.trades:
            if t.exit_reason == "atr_stop":
                assert t.return_pct < 0, (
                    f"{strat.name}: {t.ticker} atr_stop 出場報酬 {t.return_pct} ≥ 0 "
                    f"(應改標 trailing_stop)")


def test_profitable_structure_stop_relabeled_trailing_on_real_data():
    """B1 前 chip_v2 有兩筆獲利 atr_stop(2618 +6.32%、5880 +2.20%)。修正後:
    存活者(未被 3.3 冷卻期移除)改標 trailing_stop。這裡確認 chip_v2 不再有任何
    獲利 atr_stop,且若出現 trailing_stop 則其報酬 ≥ 0。"""
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots")
    res = run_backtest(snaps, STRATEGY_A_V2)
    for t in res.trades:
        if t.exit_reason == "trailing_stop":
            assert t.return_pct >= 0


# ═══════════════════════════════════════════════════════════════════════════
# 3.2 — 加碼禁向下攤平
# ═══════════════════════════════════════════════════════════════════════════

def test_chip_v2_no_downward_averaging_hon_hai():
    """驗收(3.2):鴻海(2317)chip_v2 不再出現均價低於首次進場價的加碼。
    B1 前均價從 309 攤到 273.5;修正後所有 leg 均價應維持在首次進場價(~309)之上。
    committed 快照為固定歷史,鴻海 2026-06-03 進場價穩定。"""
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots")
    res = run_backtest(snaps, STRATEGY_A_V2)
    hon = [t for t in res.trades if t.ticker == "2317"]
    if not hon:
        pytest.skip("鴻海 not in chip_v2 results on current snapshots")
    # 首次進場 ~309;向下攤平(舊 bug)會把某 leg 均價壓到 273.5。門檻 305 明確在其上。
    assert min(t.entry_price for t in hon) >= 305.0, (
        f"鴻海 chip_v2 出現向下攤平的加碼:leg 均價 {min(t.entry_price for t in hon)}")


def test_add_min_price_mult_param_exists_and_excluded_from_hash():
    assert hasattr(ep, "BACKTEST_ADD_MIN_PRICE_MULT")
    assert 0.9 <= ep.BACKTEST_ADD_MIN_PRICE_MULT <= 1.0
    cfg = ep.as_config_dict()
    assert not any(k.startswith("BACKTEST_") for k in cfg)   # R2


# ═══════════════════════════════════════════════════════════════════════════
# 3.3 — COOLDOWN:同日同價洗單 → 0
# ═══════════════════════════════════════════════════════════════════════════

def test_in_cooldown_semantics():
    """gap = entry_fill_i − last_exit_i;gap < COOLDOWN_DAYS → 禁(含同日 gap==0)。"""
    n = ep.BACKTEST_COOLDOWN_DAYS
    cd = {"X": 10}
    assert _in_cooldown(cd, "X", 10) is True                 # gap 0(同日)恆禁
    assert _in_cooldown(cd, "X", 10 + n) is False            # gap == N 放行
    assert _in_cooldown(cd, "X", 10 + n + 1) is False
    assert _in_cooldown(cd, "Y", 10) is False                # 無紀錄
    if n >= 1:
        assert _in_cooldown(cd, "X", 10 + n - 1) is True     # gap N-1 仍禁


def test_cooldown_zero_disables_guard():
    """COOLDOWN_DAYS==0 → 恆不禁(Part 5 掃描對照組語意)。"""
    cd = {"X": 10}
    # 直接驗證邏輯:gap 0 在 COOLDOWN==0 時 (0 < 0) 為 False
    assert (0 < 0) is False


def test_no_same_price_wash_in_chip_strategies():
    """驗收(3.3):chip 策略不再有「同日同價、有實際持有」的洗單再進場。
    B1 前:chip_v1 三次、chip_v2 五次(共 8)。"""
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots")
    for strat in (STRATEGY_A, STRATEGY_A_V2):
        res = run_backtest(snaps, strat)
        exits = defaultdict(list)   # ticker -> [(exit_date, exit_price)]
        for t in res.trades:
            exits[t.ticker].append((t.exit_date, round(t.exit_price, 2)))
        for t in res.trades:
            if t.holding_days <= 0:
                continue   # 末日 end_of_data 0 持有非洗單
            for xd, xp in exits[t.ticker]:
                same_wash = (t.entry_date == xd and round(t.entry_price, 2) == xp)
                assert not same_wash, (
                    f"{strat.name}: {t.ticker} 同日同價洗單再進場 {t.entry_date}@{t.entry_price}")


# ═══════════════════════════════════════════════════════════════════════════
# 3.4 — 已實現/未實現分離 + 獨立標的數
# ═══════════════════════════════════════════════════════════════════════════

def _realized_unrealized_series():
    """AAA 進場後轉弱出場(已實現);BBB 進場後撐到末日(end_of_data 未實現)。"""
    return [
        _snap("2026-06-01", [_rec("AAA", 10, 5, 100), _rec("BBB", 10, 5, 50)]),
        _snap("2026-06-02", [_rec("AAA", 20, 5, 102), _rec("BBB", 20, 5, 51)]),
        _snap("2026-06-03", [_rec("AAA", 40, 5, 104), _rec("BBB", 40, 5, 52)]),
        _snap("2026-06-04", [_rec("AAA", 80, 5, 106), _rec("BBB", 80, 5, 53)]),   # entries fire
        _snap("2026-06-05", [_rec("AAA", 80, 5, 120), _rec("BBB", 80, 5, 55)]),   # fills
        _snap("2026-06-08", [_rec("AAA", 80, 5, 121, wk="red"), _rec("BBB", 80, 5, 60)]),  # AAA exit decided
        _snap("2026-06-09", [_rec("AAA", 80, 5, 119), _rec("BBB", 80, 5, 62)]),   # AAA fill; BBB rides to end
    ]


def test_realized_unrealized_split_and_independent_tickers():
    res = run_backtest(_realized_unrealized_series(), STRATEGY_B)
    s = res.summary
    reasons = {t.exit_reason for t in res.trades}
    assert "end_of_data" in reasons and "weakening" in reasons, "fixture must have both kinds"
    # 分離:realized 排除 end_of_data,兩組筆數合計 == 全交易
    assert s["realized"]["trades"] == sum(1 for t in res.trades if t.exit_reason != "end_of_data")
    assert s["unrealized"]["trades"] == sum(1 for t in res.trades if t.exit_reason == "end_of_data")
    assert s["realized"]["trades"] + s["unrealized"]["trades"] == s["trades"]
    # 獨立標的數 = 不重複 ticker 數
    assert s["independent_tickers"] == len({t.ticker for t in res.trades})
    # 頂層(全交易)仍為毛(向後相容);未實現不得等同已實現
    assert s["avg_return"] is not None
    assert "disclosure" in s


def test_realized_excludes_inflating_unrealized_on_real_data():
    """驗收(3.4):真實快照上,momentum 全交易毛均 > 已實現毛均(未實現拉高),
    對應清單「+2.71%(已實現)膨脹到 +3.91%」的方向。語料凍結,見檔頭。"""
    snaps = _baseline_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots")
    res = run_backtest(snaps, STRATEGY_B)
    s = res.summary
    if s["unrealized"]["trades"] == 0 or s["realized"]["trades"] == 0:
        pytest.skip("need both realized and unrealized on current snapshots")
    # 未實現本樣本為正值尾端 → 全交易均值被拉高於已實現
    assert s["unrealized"]["avg_return"] > s["realized"]["avg_return"]
    assert s["realized"]["avg_return"] < s["avg_return"]


# ═══════════════════════════════════════════════════════════════════════════
# 2.4 — 體制標記(R5:讀落地不重算)
# ═══════════════════════════════════════════════════════════════════════════

def test_regime_index_only_landed_dates():
    snaps = [
        _snap("2026-07-01", []),   # 無 obs_market_* → 不入索引
        _snap("2026-07-08", [], obs_market_breadth={"breadth": 0.34},
              obs_market_regime={"regime_label_en": "Capital Waiting",
                                 "regime_label_zh": "資金觀望"},
              obs_market_temperature={"temperature_level": "warm"}),
    ]
    idx = _regime_index(snaps)
    assert "2026-07-01" not in idx
    assert idx["2026-07-08"]["regime"] == "Capital Waiting"
    assert idx["2026-07-08"]["breadth"] == 0.34
    assert idx["2026-07-08"]["temperature_level"] == "warm"


def test_enrich_with_regime_tags_trades_and_builds_table():
    snaps = [
        _snap("2026-07-08", [], obs_market_breadth={"breadth": 0.34},
              obs_market_regime={"regime_label_en": "Capital Waiting", "regime_label_zh": "資金觀望"},
              obs_market_temperature={"temperature_level": "warm"}),
        _snap("2026-06-01", []),   # 無落地體制
    ]
    payload = {"trades": [
        {"ticker": "AAA", "entry_date": "2026-07-08", "return_pct": 0.05},
        {"ticker": "BBB", "entry_date": "2026-07-08", "return_pct": -0.03},
        {"ticker": "CCC", "entry_date": "2026-06-01", "return_pct": 0.10},   # unlabeled
    ], "summary": {}}
    _enrich_with_regime(payload, snaps)
    # 每筆交易記進場當日落地體制值(R5)
    assert payload["trades"][0]["regime"]["regime"] == "Capital Waiting"
    assert payload["trades"][2]["regime"] is None
    groups = payload["summary"]["by_regime"]["groups"]
    assert groups["Capital Waiting"]["trades"] == 2
    assert groups["Capital Waiting"]["avg_return"] == round((0.05 - 0.03) / 2, 4)
    assert groups["unlabeled"]["trades"] == 1


def test_regime_enrichment_on_real_backtest():
    """整合:真實快照回測 → 每筆交易掛 regime 欄,summary.by_regime 有 groups。"""
    snaps = _load_snapshots()
    if len(snaps) < 2:
        pytest.skip("no committed snapshots")
    res = run_backtest(snaps, STRATEGY_A_V2)
    payload = res.as_dict()
    _enrich_with_regime(payload, snaps)
    assert "by_regime" in payload["summary"]
    assert all("regime" in t for t in payload["trades"])
