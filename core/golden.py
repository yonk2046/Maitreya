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
from core.market_context import dual_cost_anchor
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
    # P0.7: hard tier caps applied after scoring (audit trail; separate from
    # gates_fail so near-miss semantics are unaffected)
    tier_caps:       list[str] = field(default_factory=list)

    # Days tracking
    days_in_sm_state: int = 0
    sm_state_entered: str | None = None

    # Cost / price
    main_force_cost:  float | None = None   # avg buy cost from latest snapshot
    current_price:    float | None = None   # latest closing price

    # P0.6 dual-anchor cost (display/intelligence layer; schema at P3b)
    cost_episode_weighted: float | None = None  # volume-weighted episode entry base
    cost_conservative:     float | None = None  # min(recent, episode) — gate anchor
    cost_divergence_pct:   float | None = None  # recent vs episode, %
    cost_diverged:         bool = False         # ⚠ 成本背離 (latecomer chasing)

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
            "tier_caps":          self.tier_caps,
            "main_force_cost":    self.main_force_cost,
            "current_price":      self.current_price,
            "cost_episode_weighted": self.cost_episode_weighted,
            "cost_conservative":     self.cost_conservative,
            "cost_divergence_pct":   self.cost_divergence_pct,
            "cost_diverged":         self.cost_diverged,
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


# ── Tier caps — hard gates applied AFTER scoring ──────────────────────────────

def _load_fii_alignment_cfg() -> dict:
    """gates.fii_alignment from config/scd.example.yaml (P0.7).

    Reference-data load with safe defaults — golden layer must not crash
    when the config file is absent (e.g. minimal test environments).
    """
    try:
        import yaml
        cfg_file = _AI_STOCK / "config" / "scd.example.yaml"
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        fa = cfg.get("gates", {}).get("fii_alignment", {}) or {}
        return {
            "enabled": bool(fa.get("enabled", True)),
            "contra_days_cap": int(fa.get("contra_days_cap", 2)),
        }
    except Exception:
        return {"enabled": True, "contra_days_cap": 2}


_FII_ALIGNMENT_CFG: dict | None = None


def _fii_alignment_cfg() -> dict:
    global _FII_ALIGNMENT_CFG
    if _FII_ALIGNMENT_CFG is None:
        _FII_ALIGNMENT_CFG = _load_fii_alignment_cfg()
    return _FII_ALIGNMENT_CFG


def _reset_fii_alignment_cfg() -> None:
    """Test hook."""
    global _FII_ALIGNMENT_CFG
    _FII_ALIGNMENT_CFG = None


def _fii_contra_streak(ticker: str, snapshots: list[dict]) -> int:
    """Consecutive trailing snapshots with fii_net_buy < 0 for this ticker.

    None (no data) and absence both BREAK the streak — missing data is not
    evidence of foreign-investor selling (cf. SKELETON philosophy: thin data
    must not be treated as a signal in either direction).
    """
    n = 0
    for snap in reversed(snapshots):
        rec = next((s for s in snap.get("stocks", [])
                    if s.get("ticker") == ticker), None)
        if rec is None:
            break
        fii = rec.get("fii_net_buy")
        if fii is None or fii >= 0:
            break
        n += 1
    return n


def _apply_tier_caps(
    tier: str,
    stock_data: dict,
    fii_contra: int,
) -> tuple[str, list[str]]:
    """Hard caps applied after _tier_from_score. Returns (tier, cap_reasons).

    1. SKELETON gate (Schema v1.5): confidence_tier == SKELETON (< 50% of key
       fields populated) cannot reach PRIME — thin evidence caps at STRONG.
    2. FII alignment gate (P0.7, SCD 雙引擎 V3 章程): foreign investors
       net-selling for ≥ gates.fii_alignment.contra_days_cap consecutive
       snapshots vetoes PRIME — 外資與主力同向 is a NECESSARY condition for
       top tier, not a 2/3 soft vote.
    """
    reasons: list[str] = []

    if tier == TIER_PRIME_KEY and stock_data.get("confidence_tier") == "SKELETON":
        tier = TIER_STRONG_KEY
        reasons.append("CAP_skeleton_data")

    fa = _fii_alignment_cfg()
    if (tier == TIER_PRIME_KEY
            and fa["enabled"]
            and fii_contra >= fa["contra_days_cap"]):
        tier = TIER_STRONG_KEY
        reasons.append(f"CAP_fii_contra_{fii_contra}d")

    return tier, reasons


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

        # Hard tier caps (SKELETON data gate + P0.7 FII alignment gate).
        # Recorded in entry.tier_caps for auditability — kept OUT of
        # gates_fail so near-miss (len==1) semantics are unaffected.
        stock_data = latest_stock_map.get(ticker, {})
        tier, cap_reasons = _apply_tier_caps(
            tier, stock_data, _fii_contra_streak(ticker, snapshots))

        # P0.6 dual-anchor cost (display layer; gate consumers should read
        # cost_conservative per config gates.cost_safety.anchor)
        anchors = dual_cost_anchor(ticker, snapshots)

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
            tier_caps=cap_reasons,
            main_force_cost=latest_stock_map.get(ticker, {}).get("main_force_cost"),
            current_price=latest_stock_map.get(ticker, {}).get("current_price"),
            cost_episode_weighted=anchors["cost_episode_weighted"],
            cost_conservative=anchors["cost_conservative"],
            cost_divergence_pct=anchors["divergence_pct"],
            cost_diverged=anchors["diverged"],
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


# ── P2: Action grouping (行動分組) ────────────────────────────────────────────
# Business logic for the golden-list redesign lives HERE per the AI_GOVERNANCE
# red line (UI renders, core decides). The viewer maps each entry to exactly
# one action group and sorts groups by execution priority, not score.

ACTION_EXECUTABLE    = "executable"      # 🟢 可執行 — 結構好且價格在保守錨容忍內
ACTION_WAIT_PULLBACK = "wait_pullback"   # 🟡 等回檔 — 結構好但現價超出成本容忍
ACTION_DATA_PENDING  = "data_pending"    # 🔵 資料待補 — SKELETON / 缺價格或成本錨
ACTION_WEAKENING     = "weakening"       # 🔻 動能轉弱 — 轉弱紅橙燈或疑似出貨

ACTION_ORDER = [ACTION_EXECUTABLE, ACTION_WAIT_PULLBACK,
                ACTION_DATA_PENDING, ACTION_WEAKENING]

ACTION_META = {
    ACTION_EXECUTABLE:    {"icon": "🟢", "zh": "可執行",   "en": "Executable",    "color": "#52B788"},
    ACTION_WAIT_PULLBACK: {"icon": "🟡", "zh": "等回檔",   "en": "Wait Pullback", "color": "#D4C84B"},
    ACTION_DATA_PENDING:  {"icon": "🔵", "zh": "資料待補", "en": "Data Pending",  "color": "#7EB8D4"},
    ACTION_WEAKENING:     {"icon": "🔻", "zh": "動能轉弱", "en": "Weakening",     "color": "#E05C7A"},
}


def _load_cost_safety_cfg() -> dict:
    try:
        import yaml
        cfg = yaml.safe_load(
            (_AI_STOCK / "config" / "scd.example.yaml").read_text(encoding="utf-8")) or {}
        cs = cfg.get("gates", {}).get("cost_safety", {}) or {}
        return {"max_premium_ratio": float(cs.get("max_premium_ratio", 1.05))}
    except Exception:
        return {"max_premium_ratio": 1.05}


_COST_SAFETY_CFG: dict | None = None


def _cost_safety_cfg() -> dict:
    global _COST_SAFETY_CFG
    if _COST_SAFETY_CFG is None:
        _COST_SAFETY_CFG = _load_cost_safety_cfg()
    return _COST_SAFETY_CFG


def action_group(entry: "GoldenEntry", weakening_severity: str = "none") -> str:
    """Assign one action group to a gate-passing golden entry.

    Priority (first match wins):
      1. WEAKENING     — weakening severity red/orange, or SM 疑似出貨
      2. DATA_PENDING  — SKELETON-capped / thin data / missing price or anchor
      3. EXECUTABLE    — price ≤ cost_conservative × max_premium_ratio
      4. WAIT_PULLBACK — otherwise (structure fine, price extended)

    Note: 動能減速 (decelerating) is a yellow NEUTRAL state — it does not
    force the weakening group; its badge still shows on the card.
    """
    if weakening_severity in ("red", "orange") or entry.sm_state == "distributing":
        return ACTION_WEAKENING

    if "CAP_skeleton_data" in (entry.tier_caps or []):
        return ACTION_DATA_PENDING

    price  = entry.current_price
    anchor = entry.cost_conservative if entry.cost_conservative is not None \
        else entry.main_force_cost
    if not price or not anchor or anchor <= 0:
        return ACTION_DATA_PENDING

    if price <= anchor * _cost_safety_cfg()["max_premium_ratio"]:
        return ACTION_EXECUTABLE
    return ACTION_WAIT_PULLBACK
