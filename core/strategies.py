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
    enabled=False,   # flip on once gates/golden are wired
)

ALL_STRATEGIES = {s.name: s for s in (STRATEGY_B, STRATEGY_A)}
