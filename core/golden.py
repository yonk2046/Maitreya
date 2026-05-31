"""SCD Engine — Golden Layer v2  (STEP 7)
黃金名單 v2

The core value module. Synthesises signals from:
  • Funnel Engine     (core/funnel.py)     — structural qualification
  • State Machine     (core/state_machine.py) — lifecycle confirmation
  • Weighted scoring  — multi-dimensional conviction

Pure observation. No trading signals. No buy/sell recommendations.
Deterministic: same snapshot inputs → same output, always.

────────────────────────────────────────────────────────────────────────
Required Gates (ALL must pass to enter the Golden Layer)
────────────────────────────────────────────────────────────────────────
  G1  Funnel layer = "confirmation"
        streak ≥ 2, sector relatively strong, no failed breakout
  G2  State Machine state ∈ {confirmed, strengthening}
  G3  Sponsorship score ≥ GOLD_SPON_MIN  (default 0.45)
  G4  Transition risk ≠ "critical"
  G5  Net cumulative > 0  (still net positive)

────────────────────────────────────────────────────────────────────────
Conviction Score  0.0 – 1.0  (higher = more evidence aligned)
────────────────────────────────────────────────────────────────────────
  +0.25  streak ≥ SCORE_STREAK_HIGH  (5)
  +0.15  streak ≥ SCORE_STREAK_MID   (3)  [stacks with above if ≥5]
  +0.20  sponsorship ≥ SCORE_SPON_HIGH  (0.70)
  +0.10  sponsorship ≥ SCORE_SPON_MID   (0.55)  [stacks]
  +0.15  state == confirmed  (vs. strengthening)
  +0.10  is_tier_a  (Tier A permanent watchlist)
  +0.10  velocity_3d > 0
  +0.05  acceleration > 0
  +0.05  sector in top-3  (tighter than the top-5 gate)

Scores are capped at 1.0.

────────────────────────────────────────────────────────────────────────
Tiers
────────────────────────────────────────────────────────────────────────
  PRIME      conviction ≥ TIER_PRIME   (0.65)  — high conviction
  STRONG     conviction ≥ TIER_STRONG  (0.40)  — solid structure
  QUALIFIED  conviction ≥ 0.0          — gate-passing, lower conviction

────────────────────────────────────────────────────────────────────────
Public API
────────────────────────────────────────────────────────────────────────
  run(snapshots)                        → GoldenResult
  conviction_score(ticker, snapshots)  → float
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass, field
from typing import Any

_HERE     = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.funnel       import run as funnel_run, LAYER_CONFIRMATION, FunnelResult
from core.state_machine import run_all as sm_run_all, S_CONFIRMED, S_STRENGTHENING
from core.watchlists   import TIER_A

# ── Tunable thresholds ────────────────────────────────────────────────────────
GOLD_SPON_MIN       = 0.45   # Gate G3: minimum sponsorship to enter

SCORE_STREAK_HIGH   = 5      # +0.25 if streak ≥ this
SCORE_STREAK_MID    = 3      # +0.15 if streak ≥ this
SCORE_SPON_HIGH     = 0.70   # +0.20 if sponsorship ≥ this
SCORE_SPON_MID      = 0.55   # +0.10 if sponsorship ≥ this

TIER_PRIME          = 0.65   # conviction ≥ this → PRIME
TIER_STRONG         = 0.40   # conviction ≥ this → STRONG

SECTOR_TOP_N_TIGHT  = 3      # for +0.05 bonus (tighter than gate's top-5)

# ── Tier keys ─────────────────────────────────────────────────────────────────
TIER_PRIME_KEY      = "prime"
TIER_STRONG_KEY     = "strong"
TIER_QUALIFIED_KEY  = "qualified"

TIER_ZH = {
    TIER_PRIME_KEY:     "頂級黃金",
    TIER_STRONG_KEY:    "強勢確認",
    TIER_QUALIFIED_KEY: "入選合格",
}

TIER_EN = {
    TIER_PRIME_KEY:     "Prime",
    TIER_STRONG_KEY:    "Strong",
    TIER_QUALIFIED_KEY: "Qualified",
}

TIER_COLOR = {
    TIER_PRIME_KEY:     "#F4C842",   # gold
    TIER_STRONG_KEY:    "#52B788",   # green
    TIER_QUALIFIED_KEY: "#7EB8D4",   # blue
}

TIER_ICON = {
    TIER_PRIME_KEY:     "★",
    TIER_STRONG_KEY:    "◆",
    TIER_QUALIFIED_KEY: "●",
}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class GoldenEntry:
    """One ticker in the Golden Layer."""
    ticker:          str
    name:            str
    tier:            str   # prime / strong / qualified
    tier_zh:         str
    tier_en:         str
    tier_color:      str
    conviction:      float         # 0.0 – 1.0

    # Source states
    funnel_layer:    str           # "confirmation"
    sm_state:        str           # "confirmed" | "strengthening"
    sm_state_zh:     str
    sm_state_color:  str
    transition_risk: str
    transition_risk_zh: str
    transition_risk_color: str

    # Key metrics
    streak:            int
    net_cumulative:    int
    velocity_3d:       float | None
    acceleration:      float | None
    sponsorship_score: float
    sector:            str
    is_tier_a:         bool

    # Gate pass/fail detail  (for transparency / debugging)
    gates_passed:    list[str] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)

    # Days tracking
    days_in_sm_state: int = 0
    sm_state_entered: str | None = None

    # Cost / price
    main_force_cost:  float | None = None   # avg buy cost from latest snapshot
    current_price:    float | None = None   # latest closing price

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker":           self.ticker,
            "name":             self.name,
            "tier":             self.tier,
            "tier_zh":          self.tier_zh,
            "tier_en":          self.tier_en,
            "tier_color":       self.tier_color,
            "conviction":       round(self.conviction, 3),
            "funnel_layer":     self.funnel_layer,
            "sm_state":         self.sm_state,
            "sm_state_zh":      self.sm_state_zh,
            "sm_state_color":   self.sm_state_color,
            "transition_risk":  self.transition_risk,
            "transition_risk_zh":    self.transition_risk_zh,
            "transition_risk_color": self.transition_risk_color,
            "streak":             self.streak,
            "net_cumulative":     self.net_cumulative,
            "velocity_3d":        self.velocity_3d,
            "acceleration":       self.acceleration,
            "sponsorship_score":  self.sponsorship_score,
            "sector":             self.sector,
            "is_tier_a":          self.is_tier_a,
            "days_in_sm_state":   self.days_in_sm_state,
            "sm_state_entered":   self.sm_state_entered,
            "gates_passed":       self.gates_passed,
            "score_breakdown":    self.score_breakdown,
            "main_force_cost":    self.main_force_cost,
            "current_price":      self.current_price,
        }


@dataclass
class GoldenResult:
    date:           str
    snapshot_count: int

    prime:          list[GoldenEntry] = field(default_factory=list)
    strong:         list[GoldenEntry] = field(default_factory=list)
    qualified:      list[GoldenEntry] = field(default_factory=list)

    # Near-miss: passed G1+G2 but failed G3/G4/G5 — useful for watchlist
    near_miss:      list[GoldenEntry] = field(default_factory=list)

    @property
    def all_golden(self) -> list[GoldenEntry]:
        """All gate-passing entries, ordered by conviction desc."""
        return sorted(
            self.prime + self.strong + self.qualified,
            key=lambda e: -e.conviction,
        )

    @property
    def total(self) -> int:
        return len(self.prime) + len(self.strong) + len(self.qualified)

    def as_dict(self) -> dict[str, Any]:
        return {
            "date":           self.date,
            "snapshot_count": self.snapshot_count,
            "counts": {
                "prime":     len(self.prime),
                "strong":    len(self.strong),
                "qualified": len(self.qualified),
                "near_miss": len(self.near_miss),
                "total":     self.total,
            },
            "prime":     [e.as_dict() for e in self.prime],
            "strong":    [e.as_dict() for e in self.strong],
            "qualified": [e.as_dict() for e in self.qualified],
            "near_miss": [e.as_dict() for e in self.near_miss],
        }


# ── Conviction scorer ─────────────────────────────────────────────────────────

def _score_conviction(
    ticker: str,
    streak: int,
    sponsorship: float,
    sm_state: str,
    is_tier_a: bool,
    velocity_3d: float | None,
    acceleration: float | None,
    sector: str,
    sector_rank_latest: list[str],
) -> tuple[float, dict[str, float]]:
    """
    Compute conviction score and return (score, breakdown_dict).
    Score components are additive, capped at 1.0.
    """
    breakdown: dict[str, float] = {}

    # Streak component
    if streak >= SCORE_STREAK_HIGH:
        breakdown["streak_high"] = 0.25
        breakdown["streak_mid"]  = 0.15   # both tiers stack
    elif streak >= SCORE_STREAK_MID:
        breakdown["streak_mid"]  = 0.15

    # Sponsorship component
    if sponsorship >= SCORE_SPON_HIGH:
        breakdown["spon_high"] = 0.20
        breakdown["spon_mid"]  = 0.10    # both tiers stack
    elif sponsorship >= SCORE_SPON_MID:
        breakdown["spon_mid"] = 0.10

    # State bonus
    if sm_state == S_CONFIRMED:
        breakdown["state_confirmed"] = 0.15

    # Tier A bonus
    if is_tier_a:
        breakdown["tier_a"] = 0.10

    # Velocity
    if velocity_3d is not None and velocity_3d > 0:
        breakdown["velocity_positive"] = 0.10

    # Acceleration
    if acceleration is not None and acceleration > 0:
        breakdown["acceleration_positive"] = 0.05

    # Tight sector rank bonus
    if sector and sector in sector_rank_latest[:SECTOR_TOP_N_TIGHT]:
        breakdown["sector_top3"] = 0.05

    score = min(1.0, sum(breakdown.values()))
    return score, breakdown


# ── Gate evaluator ────────────────────────────────────────────────────────────

def _evaluate_gates(
    funnel_layer:    str,
    sm_state:        str,
    sponsorship:     float,
    transition_risk: str,
    net_cumulative:  int,
) -> tuple[bool, list[str], list[str]]:
    """
    Evaluate the 5 required gates.
    Returns (all_passed, passed_list, failed_list).
    """
    gates_pass: list[str] = []
    gates_fail: list[str] = []

    def _check(key: str, condition: bool) -> None:
        (gates_pass if condition else gates_fail).append(key)

    _check("G1_funnel_confirmation",  funnel_layer == LAYER_CONFIRMATION)
    _check("G2_state_confirmed_or_strengthening", sm_state in (S_CONFIRMED, S_STRENGTHENING))
    _check("G3_sponsorship",          sponsorship >= GOLD_SPON_MIN)
    _check("G4_risk_not_critical",    transition_risk != "critical")
    _check("G5_net_positive",         net_cumulative > 0)

    return (len(gates_fail) == 0), gates_pass, gates_fail


def _tier_from_score(conviction: float) -> str:
    if conviction >= TIER_PRIME:
        return TIER_PRIME_KEY
    if conviction >= TIER_STRONG:
        return TIER_STRONG_KEY
    return TIER_QUALIFIED_KEY


# ── Sector rank helper ────────────────────────────────────────────────────────

def _latest_sector_rank(snapshots: list[dict]) -> list[str]:
    """
    Build a sector rank list from the latest snapshot using raw net_mfb totals.
    Returns ordered list of sector names (highest net first).
    Quick approximation — avoids importing sector_intelligence for a single call.
    """
    if not snapshots:
        return []
    from core.sector_intelligence import build_sector_map, _collect_per_snap
    sm  = build_sector_map(snapshots)
    per = _collect_per_snap(snapshots, sm)
    if not per:
        return []
    latest = per[-1]["sector_data"]
    ranked = sorted(
        latest.keys(),
        key=lambda s: -sum(latest[s].get("mfb_vals", []) or [0]),
    )
    return ranked


# ── Main public API ───────────────────────────────────────────────────────────

def run(snapshots: list[dict]) -> GoldenResult:
    """
    Run the full Golden Layer v2 over all snapshots.
    Returns a GoldenResult with tickers ranked by conviction within each tier.
    """
    if not snapshots:
        return GoldenResult(date="—", snapshot_count=0)

    date = snapshots[-1].get("date", "?")

    # Run both upstream engines
    funnel_result: FunnelResult = funnel_run(snapshots)
    sm_states = sm_run_all(snapshots)

    # Build quick funnel lookup: ticker → CandidateRecord
    funnel_map = {}
    for layer_list in [
        funnel_result.discovery,
        funnel_result.observation,
        funnel_result.confirmation,
        funnel_result.risk_warning,
        funnel_result.failure,
    ]:
        for cr in layer_list:
            funnel_map[cr.ticker] = cr

    # Build latest sector rank (for conviction bonus)
    sector_rank = _latest_sector_rank(snapshots)

    # Build cost / price lookup from latest snapshot
    latest_stock_map: dict[str, dict] = {
        s["ticker"]: s
        for s in snapshots[-1].get("stocks", [])
        if "ticker" in s
    }

    result = GoldenResult(date=date, snapshot_count=len(snapshots))

    # Only tickers that appear in both engines
    all_tickers = set(funnel_map.keys()) | set(sm_states.keys())

    for ticker in sorted(all_tickers):
        cr  = funnel_map.get(ticker)
        ts  = sm_states.get(ticker)

        if cr is None or ts is None:
            continue

        f_layer  = cr.layer
        sm_state = ts.state
        spon     = cr.sponsorship_score
        risk     = ts.transition_risk
        net_cum  = cr.net_cumulative

        all_passed, gates_pass, gates_fail = _evaluate_gates(
            f_layer, sm_state, spon, risk, net_cum
        )

        conviction, breakdown = _score_conviction(
            ticker=ticker,
            streak=cr.streak,
            sponsorship=spon,
            sm_state=sm_state,
            is_tier_a=ticker in TIER_A,
            velocity_3d=cr.velocity_3d,
            acceleration=cr.acceleration,
            sector=cr.sector,
            sector_rank_latest=sector_rank,
        )

        tier = _tier_from_score(conviction)

        entry = GoldenEntry(
            ticker=ticker,
            name=cr.name,
            tier=tier,
            tier_zh=TIER_ZH[tier],
            tier_en=TIER_EN[tier],
            tier_color=TIER_COLOR[tier],
            conviction=conviction,
            funnel_layer=f_layer,
            sm_state=sm_state,
            sm_state_zh=ts.state_zh,
            sm_state_color=ts.state_color,
            transition_risk=risk,
            transition_risk_zh=ts.transition_risk_zh,
            transition_risk_color=ts.transition_risk_color,
            streak=cr.streak,
            net_cumulative=net_cum,
            velocity_3d=cr.velocity_3d,
            acceleration=cr.acceleration,
            sponsorship_score=spon,
            sector=cr.sector,
            is_tier_a=ticker in TIER_A,
            days_in_sm_state=ts.days_in_state,
            sm_state_entered=ts.state_entered,
            gates_passed=gates_pass,
            score_breakdown=breakdown,
            main_force_cost=latest_stock_map.get(ticker, {}).get("main_force_cost"),
            current_price=latest_stock_map.get(ticker, {}).get("current_price"),
        )

        if all_passed:
            if tier == TIER_PRIME_KEY:
                result.prime.append(entry)
            elif tier == TIER_STRONG_KEY:
                result.strong.append(entry)
            else:
                result.qualified.append(entry)
        elif len(gates_fail) == 1:
            # Near miss: only one gate failed — still worth surfacing
            result.near_miss.append(entry)

    # Sort by conviction desc within each tier
    def _sort(lst: list[GoldenEntry]) -> list[GoldenEntry]:
        return sorted(lst, key=lambda e: (-e.conviction, -e.streak, -(e.net_cumulative or 0)))

    result.prime     = _sort(result.prime)
    result.strong    = _sort(result.strong)
    result.qualified = _sort(result.qualified)
    result.near_miss = _sort(result.near_miss)

    return result


def conviction_score(ticker: str, snapshots: list[dict]) -> float:
    """
    Fast single-ticker conviction score (0.0–1.0).
    Returns 0.0 if ticker is not in the Golden Layer.
    """
    gr = run(snapshots)
    for e in gr.all_golden:
        if e.ticker == ticker:
            return e.conviction
    return 0.0


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json
    import argparse

    from tools.temporal._loader import load_snapshot, real_dates

    dates = real_dates()
    snaps: list[dict] = []
    for d in dates:
        try:
            snaps.append(load_snapshot(d))
        except Exception:
            pass

    if not snaps:
        print("No snapshots found.")
        import sys; sys.exit(1)

    p = argparse.ArgumentParser(description="SCD Golden Layer v2")
    p.add_argument("--json",      action="store_true", help="JSON output")
    p.add_argument("--near-miss", action="store_true", help="Also show near-miss entries")
    p.add_argument("--ticker",    default=None,        help="Single ticker detail")
    args = p.parse_args()

    gr = run(snaps)

    if args.json:
        print(_json.dumps(gr.as_dict(), ensure_ascii=False, indent=2, default=str))
        import sys; sys.exit(0)

    W = 70
    total = gr.total

    print(f"\n{'═'*W}")
    print(f"  黃金名單 v2  GOLDEN LAYER v2  {gr.date}  ({gr.snapshot_count} snapshots)")
    print(f"{'═'*W}")
    print(f"  ★ 頂級黃金 Prime={len(gr.prime)}  "
          f"◆ 強勢確認 Strong={len(gr.strong)}  "
          f"● 入選合格 Qualified={len(gr.qualified)}  "
          f"[Near-miss={len(gr.near_miss)}]")

    if args.ticker:
        # Single-ticker deep-dive
        t = args.ticker.strip()
        found = next((e for e in gr.all_golden if e.ticker == t), None)
        if found is None:
            # Check near-miss
            found = next((e for e in gr.near_miss if e.ticker == t), None)
            if found:
                print(f"\n  ⚠ {t} is a near-miss (failed 1 gate)")
            else:
                print(f"\n  {t} not found in Golden Layer or near-miss list.")
                import sys; sys.exit(0)
        e = found
        print(f"\n{'─'*W}")
        print(f"  {TIER_ICON[e.tier]} {e.ticker} {e.name}  [{e.tier_zh} / {e.tier_en}]")
        print(f"  Conviction: {e.conviction:.2f}  Risk: {e.transition_risk_zh}")
        print(f"  Funnel: {e.funnel_layer}  State: {e.sm_state_zh}  {e.days_in_sm_state}日")
        print(f"  連買 {e.streak}日  累計 {e.net_cumulative:+,}張  贊助 {e.sponsorship_score:.2f}")
        print(f"  Gates passed: {', '.join(e.gates_passed)}")
        print(f"  Score breakdown:")
        for k, v in e.score_breakdown.items():
            print(f"    {k:<28} +{v:.2f}")
        import sys; sys.exit(0)

    def _print_tier(
        entries: list[GoldenEntry],
        icon: str,
        title_zh: str,
        title_en: str,
        near: bool = False,
    ) -> None:
        if not entries:
            return
        label = "近乎入選 Near-Miss" if near else f"{title_zh} {title_en}"
        print(f"\n── {icon} {label} ({len(entries)}) {'─'*(W - len(label) - 7)}")
        for e in entries:
            tier_a = "[A]" if e.is_tier_a else "   "
            vel_str = (f"v{e.velocity_3d:+,.0f}" if e.velocity_3d is not None else "v——")
            risk_sym = {"low": "○", "medium": "◑", "elevated": "●", "critical": "⚠"}.get(e.transition_risk, "?")
            print(
                f"  {risk_sym} {tier_a} {e.ticker} {e.name:<10}  "
                f"★{e.conviction:.2f}  {e.sm_state_zh:<6}  "
                f"連買{e.streak}日  累計{e.net_cumulative:+,}張  "
                f"贊助{e.sponsorship_score:.2f}  {vel_str}"
            )

    _print_tier(gr.prime,     "★", "頂級黃金", "Prime")
    _print_tier(gr.strong,    "◆", "強勢確認", "Strong")
    _print_tier(gr.qualified, "●", "入選合格", "Qualified")

    if args.near_miss:
        _print_tier(gr.near_miss, "○", "", "", near=True)

    print()
