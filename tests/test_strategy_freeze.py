"""策略凍結守門員 —— 動到設定就紅,強迫承認前推紀錄要歸零。

2026-07-28 凍結宣告(見 docs/migration/EXEC-PLAN-backtest-arc-20260723.md §六):
往回補歷史不可行(原始觀測 2026-05-08 才開始／分點歷史不可得／補歷史必踩
look-ahead),所以唯一乾淨的樣本外只能靠**前推**——凍結當下這些資料還不存在,
任何人都不可能拿它調過參數。

前推的效力完全建立在「策略設定沒被動過」之上。設定一改,之前累積的前推 session
就不再是同一支策略的紀錄,計時必須歸零。沒有偵測機制的凍結只是註解,所以有這一檔:
**改設定 → 這裡紅 → 你必須回 EXEC-PLAN §六 補記新的凍結日與 hash。**

這不是禁止修改。是禁止**無聲**修改。
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import core.engine_params as ep          # noqa: E402
from core.hashing import canonical_sha256  # noqa: E402
from core.strategies import ALL_STRATEGIES  # noqa: E402

FREEZE_DATE = "2026-07-28"
FREEZE_HEAD = "eb7fbaf"

# dataclasses.asdict(cfg) → canonical_sha256,取前 23 字元(與 EXEC-PLAN §六 表格一致)
FROZEN_STRATEGIES = {
    "chip_anchored_swing":   "sha256:4b015a856e071041",
    "chip_anchored_v2":      "sha256:b5a2e87359921611",
    "chip_anchored_v3":      "sha256:9d98d40b61479784",
    "momentum_continuation": "sha256:a10182d22e78f733",
    "momentum_v2":           "sha256:dc25193a9ec85228",
}

# BACKTEST_* 是研究層,**不入 config_hash**(裁定 R2),所以不會被 engine_params 的
# config_hash 守到 —— 必須在這裡逐項釘死,否則改了回測參數不會有任何地方變紅。
FROZEN_BACKTEST_PARAMS = {
    "BACKTEST_ADD_MIN_PRICE_MULT": 0.98,
    "BACKTEST_COOLDOWN_DAYS": 2,
    "BACKTEST_COST_BREAK": 0.92,
    "BACKTEST_COST_CAP": 1.15,
    "BACKTEST_COST_FULL_TIER": 1.05,
    "BACKTEST_ENTRY_STOP": 0.93,
    "BACKTEST_FEE_MIN": 20.0,
    "BACKTEST_FEE_RATE": 0.000855,
    "BACKTEST_INITIAL_CAPITAL": 1_000_000.0,
    "BACKTEST_POSITION_SIZE": 100_000.0,
    "BACKTEST_TAX_RATE": 0.003,
}

_REMEDY = (
    f"\n\n策略設定已偏離 {FREEZE_DATE} 的凍結基線(HEAD {FREEZE_HEAD})。"
    "\n如果這是有意的變更,請到 docs/migration/EXEC-PLAN-backtest-arc-20260723.md §六:"
    "\n  1. 補記新的凍結日與 hash"
    "\n  2. 明確宣告前推樣本外計時歸零(之前累積的 session 不再是同一支策略的紀錄)"
    "\n  3. 同步更新本檔的 FROZEN_* 常數"
    "\n判斷參數的變更另需走修正案流程並取得 Yonki 核准。"
)


@pytest.mark.parametrize("name", sorted(FROZEN_STRATEGIES))
def test_strategy_config_matches_freeze(name):
    cfg = ALL_STRATEGIES[name]
    got = canonical_sha256(dataclasses.asdict(cfg))
    assert got.startswith(FROZEN_STRATEGIES[name]), (
        f"{name} 設定已變更:{got[:23]}… ≠ 凍結值 {FROZEN_STRATEGIES[name]}…{_REMEDY}")


def test_no_strategy_added_or_removed():
    assert set(ALL_STRATEGIES) == set(FROZEN_STRATEGIES), (
        f"策略清單變動:新增 {set(ALL_STRATEGIES) - set(FROZEN_STRATEGIES)}、"
        f"移除 {set(FROZEN_STRATEGIES) - set(ALL_STRATEGIES)}{_REMEDY}")


def test_backtest_params_match_freeze():
    drift = {k: (v, getattr(ep, k, None)) for k, v in FROZEN_BACKTEST_PARAMS.items()
             if getattr(ep, k, None) != v}
    assert not drift, (
        "回測參數偏離凍結值(凍結值, 現值):"
        + "".join(f"\n  {k}: {a} → {b}" for k, (a, b) in sorted(drift.items()))
        + _REMEDY)
