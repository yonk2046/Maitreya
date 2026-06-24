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
