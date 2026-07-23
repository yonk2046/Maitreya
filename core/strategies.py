"""core/strategies.py — paper-trading / backtest strategy definitions (P3b).

Strategy rules live here as data (dataclass configs), never hardcoded inside the
engine — per the governance redline (rules in config, engine in core, viewer
renders). The engine (core/paper_trading.py) reads a StrategyConfig and applies
it deterministically.

Two strategies from PAPER_TRADING_SPEC_20260624:
  A 籌碼錨定波段 (chip-anchored swing) — conservative, needs the golden gate
    (P3b scoring). Defined but its entry is gated until scoring is wired.
  B 動能延續 (momentum continuation) — runnable today: entry/exit are purely
    temporal + weakening, which the snapshot chain already provides.

Tunable params (spec §3) carry defaults here and may later move to
config/scd.example.yaml; the point is they are NOT buried in the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    kind: str                       # "momentum" | "chip_anchored"
    zh: str = ""

    # ── Entry ──────────────────────────────────────────────────────────────
    entry_streak_min: int = 3        # 連買門檻 (spec ENTRY_STREAK_MIN, scan {3,4,5})
    require_velocity_positive: bool = True
    require_acceleration_positive: bool = True
    require_fii_aligned: bool = True     # 外資同向 (fii_net_buy > 0)
    max_premium_ratio: float = 1.05      # 現價 ≤ 主力成本 × this (chip-anchored entry)

    # ── Exit ───────────────────────────────────────────────────────────────
    trailing_stop_pct: float = 0.08      # 移動停利: 從波段最高回落 (momentum only)
    exit_on_weakening: tuple[str, ...] = ("orange", "red")  # 轉弱嚴重度即出
    fii_reversal_days: int = 2           # 外資連 N 日反向 → 出
    velocity_negative_days: int = 2      # velocity_3d 連 N 日轉負 → 減碼/出

    # ── Sizing (spec setting 3: fixed position for v1) ─────────────────────
    position_unit: float = 1.0
    enabled: bool = True                 # A is disabled until gates exist

    # ── v2 partial sizing (spec §32-67) — off by default (v1 = full in/out) ──
    partial_sizing: bool = False
    add_unit: float = 0.5                # 加碼單位
    max_units: float = 2.0               # 上限
    add_cooldown_days: int = 3           # B: 每 +N 日才可再加
    add_cost_band: tuple[float, float] = (1.00, 1.02)   # A: 現價/成本 落在此帶 → 加碼
    tp1_sell_mult: float = 1.0           # A TP1: 主力賣超 > 吸籌均買 × 此 → 減半
    structure_low_window: int = 10       # A: 結構低點回看窗 (最低收盤)
    atr_window: int = 14                 # A: ATR 視窗 (收盤對收盤代理,因無 high/low)
    atr_buffer_mult: float = 0.5         # A: 止損緩衝 = 此 × ATR%


# 動能延續 — runnable now (temporal + weakening only).
STRATEGY_B = StrategyConfig(
    name="momentum_continuation",
    zh="動能延續",
    kind="momentum",
    entry_streak_min=3,
    require_velocity_positive=True,
    require_acceleration_positive=True,
    require_fii_aligned=True,
    trailing_stop_pct=0.08,
    exit_on_weakening=("orange", "red"),
    fii_reversal_days=2,
    enabled=True,
)

# 籌碼錨定波段 — needs the golden gate (P3b scoring). Defined now, entry gated.
STRATEGY_A = StrategyConfig(
    name="chip_anchored_swing",
    zh="籌碼錨定波段",
    kind="chip_anchored",
    entry_streak_min=3,
    max_premium_ratio=1.05,
    exit_on_weakening=("orange", "red"),
    fii_reversal_days=2,
    enabled=True,    # P3b: golden engine produces a real list → A is runnable on-the-fly
)

# ── v2 分批版（spec §32-67）────────────────────────────────────────────────
# A v2：進場1單位 → 回測貼成本(×1.00-1.02)加0.5 → TP1(主力顯著賣超/velocity轉負連2/W1·W5)減半
#       → TP2/硬止損(轉弱orange·red / W3 / 主力連2賣 / 雙引擎反向 / 跌破結構止損)全出。
# B v2：進場1單位 → velocity正且主力買超創新高、每3日加0.5(上限2) → velocity轉負連2減半
#       → 出場(移動停利8% / 轉弱orange·red / 外資連2反向)。
STRATEGY_A_V2 = StrategyConfig(
    name="chip_anchored_v2", zh="籌碼錨定波段 v2", kind="chip_anchored",
    entry_streak_min=3, max_premium_ratio=1.05,
    exit_on_weakening=("orange", "red"), fii_reversal_days=2,
    partial_sizing=True, add_unit=0.5, max_units=2.0,
    add_cost_band=(1.00, 1.02), tp1_sell_mult=1.0,
    structure_low_window=10, atr_window=14, atr_buffer_mult=0.5,
    enabled=True,
)
STRATEGY_B_V2 = StrategyConfig(
    name="momentum_v2", zh="動能延續 v2", kind="momentum",
    entry_streak_min=3, trailing_stop_pct=0.08,
    exit_on_weakening=("orange", "red"), fii_reversal_days=2,
    partial_sizing=True, add_unit=0.5, max_units=2.0, add_cooldown_days=3,
    enabled=True,
)

ALL_STRATEGIES = {s.name: s for s in
                  (STRATEGY_B, STRATEGY_A, STRATEGY_B_V2, STRATEGY_A_V2)}


# ── Shared entry judgement (single source of truth) ─────────────────────────
# 治理紅線 5:同一個進場判斷邏輯只能有一份實作。回測引擎(core/paper_trading.py)
# 與 UI 策略標示(strategy_tags_for_date)必須共用 would_enter — 不得各留一份,
# 否則標示與回測會漂移。純函數、決定論、零 I/O(golden/temporal 皆吃切片)。

def _rec_for(snap: dict, ticker: str) -> dict | None:
    for s in snap.get("stocks", []):
        if s.get("ticker") == ticker:
            return s
    return None


def would_enter(
    ticker: str,
    snapshots: list[dict],
    strategy: StrategyConfig,
    golden_result=None,
) -> tuple[bool, list[str]]:
    """回傳 (是否符合進場條件, 未通過原因清單)。

    決定論純函數。回測引擎與 UI 標示必須共用此函數(治理紅線 5)。

    snapshots: 只到判斷日為止的時間切片(oldest→newest),防前視偏誤 —— 判斷日
    = snapshots[-1],temporal 與 golden 都只吃這個切片,不看未來。
    golden_result: 可選,籌碼型策略共用同一份 golden.run(切片)以省算並與回測對齊;
    momentum 型忽略此參數。
    未通過原因(reasons)供 UI tooltip,例如 ["價/本 1.12 超出上限 1.05"]。

    布林值與舊 _momentum_entry_ok / 回測進場閘門逐條等價 —— 進場成立 iff 所有條件
    通過(reasons 為空)。
    """
    if not snapshots:
        return (False, ["無快照"])
    decide = snapshots[-1]
    prior = snapshots[:-1]
    rec = _rec_for(decide, ticker)
    if rec is None:
        return (False, ["判斷日無此標的資料"])

    if strategy.kind == "chip_anchored":
        from core import golden as _golden   # lazy: heavy funnel/state engine
        if golden_result is None:
            golden_result = _golden.run(snapshots)
        golden_map = {e.ticker: e for e in (golden_result.prime + golden_result.strong)}
        ge = golden_map.get(ticker)
        if ge is None:
            return (False, ["未進黃金名單(閘門未全過)"])
        anchor = ge.cost_conservative if ge.cost_conservative is not None else ge.main_force_cost
        price_d = rec.get("current_price")
        if not anchor or not price_d:
            return (False, ["缺主力成本錨或現價"])
        if price_d > anchor * strategy.max_premium_ratio:
            return (False, [f"價/本 {price_d / anchor:.2f} 超出上限 {strategy.max_premium_ratio:.2f}"])
        return (True, [])

    # momentum — 逐條對應舊 _momentum_entry_ok
    from core.market_context import temporal_enrich   # lazy (matches engine import)
    temporal = temporal_enrich(ticker, prior, rec)
    reasons: list[str] = []
    if temporal["main_force_consecutive_days"] < strategy.entry_streak_min:
        reasons.append(
            f"連買 {temporal['main_force_consecutive_days']} 日 < 門檻 {strategy.entry_streak_min}")
    if strategy.require_velocity_positive and not ((temporal["velocity_3d"] or 0) > 0):
        reasons.append("3日速度未轉正")
    if strategy.require_acceleration_positive and not ((temporal["acceleration"] or 0) > 0):
        reasons.append("加速度未轉正")
    if strategy.require_fii_aligned and not ((rec.get("fii_net_buy") or 0) > 0):
        reasons.append("外資未同向")
    return (not reasons, reasons)


def strategy_tags_for_date(
    snapshots: list[dict],
    strategies: dict[str, StrategyConfig],
) -> dict[str, dict]:
    """回傳 {ticker: {"tags": ["A","B"], "rejections": {"A": [...原因]}}}。

    決定論:只吃到判斷日(snapshots[-1])為止的切片。籌碼型策略共用一次
    golden.run(切片)以省算並確保與回測同名單。只收錄「至少符合一個策略」的標的
    (未符合任何策略者不列 → 對應 viewer「不顯示灰色空徽章」)。rejections 收錄該
    標的『未取得』的策略之未通過原因,供 tooltip。

    可擴充:未來加 v3 只需在 strategies dict 新增一筆(例 {"C": chip_anchored_v3}),
    UI 無需改動。
    """
    if not snapshots:
        return {}
    decide = snapshots[-1]
    # 籌碼型策略共用一份 golden.run(切片)。
    golden_result = None
    if any(cfg.kind == "chip_anchored" for cfg in strategies.values()):
        from core import golden as _golden
        golden_result = _golden.run(snapshots)

    out: dict[str, dict] = {}
    for rec in decide.get("stocks", []):
        ticker = rec.get("ticker")
        if not ticker:
            continue
        tags: list[str] = []
        rejections: dict[str, list[str]] = {}
        for label in sorted(strategies):
            cfg = strategies[label]
            gr = golden_result if cfg.kind == "chip_anchored" else None
            ok, reasons = would_enter(ticker, snapshots, cfg, golden_result=gr)
            if ok:
                tags.append(label)
            else:
                rejections[label] = reasons
        if tags:
            out[ticker] = {"tags": tags, "rejections": rejections}
    return out
