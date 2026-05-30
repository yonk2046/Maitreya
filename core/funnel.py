"""SCD Engine — Candidate Funnel Engine  (STEP 5)
候選漏斗引擎

Pure observation module. No buy/sell signals. No recommendations.
Narrows the full universe into a structured, layered watch list.

Five layers
──────────
  Layer 1  DISCOVERY      appears in ≥2 snapshots + mfb data present
  Layer 2  OBSERVATION    streak ≥ 1  OR  sponsorship_score ≥ SPON_THRESHOLD
  Layer 3  CONFIRMATION   streak ≥ 2  AND  sector relatively strong
                          AND  no failed breakout
  Layer 4  RISK_WARNING   failed breakout detected  OR  velocity turning negative
  Layer 5  FAILURE        was in Layer 3+, now streak = 0 for ≥2 consecutive days

Sector strength (Layer 3) uses relative rule:
  • current day is in top-3 sectors by net_mfb, OR
  • in last 3 available days, appeared in top-5 on ≥ 2 days

Tunable thresholds (module-level constants — change here to adjust globally):
  SPON_THRESHOLD   = 0.35   (Layer 2 sponsorship gate)
  MIN_STREAK_L2    = 1      (Layer 2 streak gate)
  MIN_STREAK_L3    = 2      (Layer 3 streak gate)
  SECTOR_TOP_N_NOW = 3      (current-day top-N for sector strength)
  SECTOR_TOP_N_3D  = 5      (3-day rolling top-N)
  SECTOR_3D_MIN    = 2      (must appear in top-N on this many of last 3 days)
  NEG_VEL_DAYS     = 2      (consecutive negative velocity days → risk warning)

Public API
──────────
  run(snapshots)                  → FunnelResult
  funnel_layer(ticker, snapshots) → single-ticker layer string
"""
from __future__ import annotations

import sys
import pathlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

_HERE     = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.market_context import (
    accumulation_velocity,
    sponsorship_persistence,
    failed_breakout_memory,
    full_ticker_context,
)
from core.sector_intelligence import (
    build_sector_map,
    _collect_per_snap,
)
from core.watchlists import TIER_A, build_name_map

# ── Tunable thresholds ────────────────────────────────────────────────────────
SPON_THRESHOLD    = 0.35
MIN_STREAK_L2     = 1
MIN_STREAK_L3     = 2
SECTOR_TOP_N_NOW  = 3
SECTOR_TOP_N_3D   = 5
SECTOR_3D_MIN     = 2
NEG_VEL_DAYS      = 2

# ── Layer keys ────────────────────────────────────────────────────────────────
LAYER_DISCOVERY    = "discovery"
LAYER_OBSERVATION  = "observation"
LAYER_CONFIRMATION = "confirmation"
LAYER_RISK_WARNING = "risk_warning"
LAYER_FAILURE      = "failure"
LAYER_UNDISCOVERED = "undiscovered"

LAYER_RANK = {
    LAYER_UNDISCOVERED: 0,
    LAYER_DISCOVERY:    1,
    LAYER_OBSERVATION:  2,
    LAYER_CONFIRMATION: 3,
    LAYER_RISK_WARNING: 4,   # parallel — can overlap with 2/3
    LAYER_FAILURE:      5,
}

LAYER_ZH = {
    LAYER_DISCOVERY:    "發現",
    LAYER_OBSERVATION:  "值得觀察",
    LAYER_CONFIRMATION: "等待確認",
    LAYER_RISK_WARNING: "風險警示",
    LAYER_FAILURE:      "結構失敗",
    LAYER_UNDISCOVERED: "未追蹤",
}

LAYER_EN = {
    LAYER_DISCOVERY:    "Discovery",
    LAYER_OBSERVATION:  "Observation",
    LAYER_CONFIRMATION: "Confirmation",
    LAYER_RISK_WARNING: "Risk Warning",
    LAYER_FAILURE:      "Failure",
    LAYER_UNDISCOVERED: "Undiscovered",
}

LAYER_COLOR = {
    LAYER_DISCOVERY:    "#4A6A80",
    LAYER_OBSERVATION:  "#7EB8D4",
    LAYER_CONFIRMATION: "#52B788",
    LAYER_RISK_WARNING: "#D4A84B",
    LAYER_FAILURE:      "#E05C7A",
    LAYER_UNDISCOVERED: "#2A3A4A",
}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class CandidateRecord:
    ticker:            str
    name:              str
    layer:             str
    layer_zh:          str
    layer_en:          str
    layer_color:       str
    days_in_layer:     int
    entered_layer_date: str | None
    prior_layer:       str | None

    # Key metrics (latest snapshot)
    streak:            int
    net_cumulative:    int
    velocity_3d:       float | None
    acceleration:      float | None
    sponsorship_score: float
    top_broker:        str | None
    top_broker_days:   int
    failed_breakout:   bool
    sector:            str
    is_tier_a:         bool

    # Risk flags
    velocity_turning_negative: bool
    days_since_last_failure:   int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker":             self.ticker,
            "name":               self.name,
            "layer":              self.layer,
            "layer_zh":           self.layer_zh,
            "layer_en":           self.layer_en,
            "layer_color":        self.layer_color,
            "days_in_layer":      self.days_in_layer,
            "entered_layer_date": self.entered_layer_date,
            "prior_layer":        self.prior_layer,
            "streak":             self.streak,
            "net_cumulative":     self.net_cumulative,
            "velocity_3d":        self.velocity_3d,
            "acceleration":       self.acceleration,
            "sponsorship_score":  self.sponsorship_score,
            "top_broker":         self.top_broker,
            "top_broker_days":    self.top_broker_days,
            "failed_breakout":    self.failed_breakout,
            "sector":             self.sector,
            "is_tier_a":          self.is_tier_a,
            "velocity_turning_negative": self.velocity_turning_negative,
            "days_since_last_failure":   self.days_since_last_failure,
        }


@dataclass
class FunnelResult:
    date:          str
    snapshot_count: int

    discovery:    list[CandidateRecord] = field(default_factory=list)
    observation:  list[CandidateRecord] = field(default_factory=list)
    confirmation: list[CandidateRecord] = field(default_factory=list)
    risk_warning: list[CandidateRecord] = field(default_factory=list)
    failure:      list[CandidateRecord] = field(default_factory=list)

    # Counts
    @property
    def total_candidates(self) -> int:
        return (len(self.discovery) + len(self.observation) +
                len(self.confirmation) + len(self.risk_warning))

    def layer_list(self, layer: str) -> list[CandidateRecord]:
        return getattr(self, layer.replace("_warning", "_warning"), [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "date":           self.date,
            "snapshot_count": self.snapshot_count,
            "counts": {
                "discovery":    len(self.discovery),
                "observation":  len(self.observation),
                "confirmation": len(self.confirmation),
                "risk_warning": len(self.risk_warning),
                "failure":      len(self.failure),
            },
            "discovery":    [r.as_dict() for r in self.discovery],
            "observation":  [r.as_dict() for r in self.observation],
            "confirmation": [r.as_dict() for r in self.confirmation],
            "risk_warning": [r.as_dict() for r in self.risk_warning],
            "failure":      [r.as_dict() for r in self.failure],
        }


# ── Sector strength helper ────────────────────────────────────────────────────

def _build_sector_rank_history(
    snapshots: list[dict],
    sm=None,
) -> list[list[str]]:
    """
    Returns per-snapshot ordered sector list (by net_mfb, desc).
    Index 0 = oldest, -1 = latest.
    """
    if sm is None:
        sm = build_sector_map(snapshots)
    per = _collect_per_snap(snapshots, sm)
    history: list[list[str]] = []
    for ps in per:
        ranked = sorted(
            ps["sector_data"].keys(),
            key=lambda s: -sum(ps["sector_data"][s].get("mfb_vals", []) or [0]),
        )
        history.append(ranked)
    return history


def _sector_is_strong(
    ticker_sector: str,
    rank_history: list[list[str]],
) -> bool:
    """
    True if ticker's sector is relatively strong:
      Option A: currently in top-SECTOR_TOP_N_NOW
      Option B: in top-SECTOR_TOP_N_3D on ≥ SECTOR_3D_MIN of last 3 days
    """
    if not rank_history:
        return False

    latest_rank = rank_history[-1]
    if ticker_sector in latest_rank[:SECTOR_TOP_N_NOW]:
        return True

    # Rolling 3-day check
    recent = rank_history[-3:]
    hits = sum(
        1 for day_rank in recent
        if ticker_sector in day_rank[:SECTOR_TOP_N_3D]
    )
    return hits >= SECTOR_3D_MIN


# ── Velocity-turning-negative helper ─────────────────────────────────────────

def _velocity_turning_negative(records: list[dict]) -> bool:
    """True if the last NEG_VEL_DAYS consecutive mfb values are negative."""
    if not records:
        return False
    tail = [r.get("main_force_buy") for r in records[-NEG_VEL_DAYS:]]
    real = [v for v in tail if v is not None]
    return len(real) >= NEG_VEL_DAYS and all(v < 0 for v in real)


# ── Layer entry date helper ───────────────────────────────────────────────────

def _days_and_entry_in_layer(
    ticker: str,
    target_layer: str,
    snapshots: list[dict],
    rank_history: list[list[str]],
    sm=None,
) -> tuple[int, str | None]:
    """
    Walk snapshots in reverse to find how long ticker has been in target_layer.
    Returns (days_in_layer, entered_date).
    Approximate — rebuilds layer assignment per date.
    """
    if sm is None:
        sm = build_sector_map(snapshots)

    days_in = 0
    entered = None

    # Walk in reverse; stop when layer changes
    for i in range(len(snapshots) - 1, -1, -1):
        sub_snaps = snapshots[: i + 1]
        if len(sub_snaps) < 2:
            break
        layer_i = _assign_layer_single(ticker, sub_snaps, rank_history[: i + 1], sm)
        if layer_i == target_layer:
            days_in += 1
            entered = snapshots[i].get("date")
        else:
            break

    return days_in, entered


def _assign_layer_single(
    ticker: str,
    snapshots: list[dict],
    rank_history: list[list[str]],
    sm=None,
) -> str:
    """Assign funnel layer for one ticker given a snapshot window."""
    if sm is None:
        sm = build_sector_map(snapshots)

    # Build per-ticker records
    records: list[dict] = []
    for snap in snapshots:
        rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
        if rec:
            records.append({**rec, "date": snap.get("date", "")})

    appearances = len(records)
    if appearances < 2:
        return LAYER_DISCOVERY if appearances == 1 else LAYER_UNDISCOVERED

    # Check mfb data availability
    mfb_vals = [r.get("main_force_buy") for r in records if r.get("main_force_buy") is not None]
    if not mfb_vals:
        return LAYER_DISCOVERY

    acc  = accumulation_velocity(ticker, records)
    sp   = sponsorship_persistence(ticker, records)
    fb   = failed_breakout_memory(ticker, records)
    ts   = sm.sector_of(ticker)

    streak  = acc["streak"]
    spon    = sp["persistence_score"]
    failed  = fb["failed_breakout_detected"]
    vel_neg = _velocity_turning_negative(records)

    # ── Risk Warning (parallel — takes precedence over positive layers) ──
    if failed or (vel_neg and streak == 0):
        return LAYER_RISK_WARNING

    # ── Failure: was accumulating/confirming, now completely gone ────────
    if streak == 0 and appearances >= 3:
        prior_streak_vals = [r.get("main_force_buy") or 0 for r in records[-4:-1]]
        if sum(1 for v in prior_streak_vals if v > 0) >= 2:
            return LAYER_FAILURE

    # ── Layer 3 — Confirmation ───────────────────────────────────────────
    sector_strong = _sector_is_strong(ts, rank_history)
    if streak >= MIN_STREAK_L3 and sector_strong and not failed:
        return LAYER_CONFIRMATION

    # ── Layer 2 — Observation ────────────────────────────────────────────
    if streak >= MIN_STREAK_L2 or spon >= SPON_THRESHOLD:
        return LAYER_OBSERVATION

    # ── Layer 1 — Discovery ──────────────────────────────────────────────
    return LAYER_DISCOVERY


# ── Main public API ───────────────────────────────────────────────────────────

def run(snapshots: list[dict]) -> FunnelResult:
    """
    Run the full funnel over all snapshots.
    Returns a FunnelResult with tickers sorted by priority within each layer.
    """
    if not snapshots:
        return FunnelResult(date="—", snapshot_count=0)

    date     = snapshots[-1].get("date", "?")
    sm       = build_sector_map(snapshots)
    rh       = _build_sector_rank_history(snapshots, sm)
    name_map = build_name_map(snapshots)

    # Collect all tickers
    all_tickers: set[str] = set()
    for snap in snapshots:
        for s in snap.get("stocks", []):
            t = s.get("ticker", "")
            if t:
                all_tickers.add(t)

    latest_stocks = {s["ticker"]: s for s in snapshots[-1].get("stocks", [])}

    # Previous snapshot for prior-layer detection
    prev_snaps = snapshots[:-1] if len(snapshots) > 1 else []

    result = FunnelResult(date=date, snapshot_count=len(snapshots))

    for ticker in sorted(all_tickers):
        # Build records for this ticker
        records: list[dict] = []
        for snap in snapshots:
            rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
            if rec:
                records.append({**rec, "date": snap.get("date", "")})

        if len(records) < 1:
            continue

        # Compute layer
        layer = _assign_layer_single(ticker, snapshots, rh, sm)
        if layer == LAYER_UNDISCOVERED:
            continue  # don't surface undiscovered

        # Prior layer
        prior_layer = None
        if prev_snaps:
            prev_rh = rh[:-1] if len(rh) > 1 else rh
            prior_layer = _assign_layer_single(ticker, prev_snaps, prev_rh, sm)
            if prior_layer == layer:
                prior_layer = None  # no change

        # Days in current layer (lightweight approximation)
        days_in = 1
        entered = snapshots[-1].get("date")
        for i in range(len(snapshots) - 2, -1, -1):
            sub  = snapshots[: i + 1]
            srh  = rh[: i + 1]
            if not sub:
                break
            l_i = _assign_layer_single(ticker, sub, srh, sm)
            if l_i == layer:
                days_in += 1
                entered = snapshots[i].get("date")
            else:
                break

        # Metrics
        mfb_vals = [r.get("main_force_buy") for r in records if r.get("main_force_buy") is not None]
        acc  = accumulation_velocity(ticker, records) if mfb_vals else {}
        sp   = sponsorship_persistence(ticker, records)
        fb   = failed_breakout_memory(ticker, records)

        # Days since last failure
        days_since_fail: int | None = None
        if not fb.get("failed_breakout_detected") and fb.get("breakout_date"):
            all_dates = [snap.get("date", "") for snap in snapshots]
            bd = fb.get("breakout_date", "")
            if bd in all_dates:
                days_since_fail = len(all_dates) - 1 - all_dates.index(bd)

        stock = latest_stocks.get(ticker, {})

        cr = CandidateRecord(
            ticker=ticker,
            name=name_map.get(ticker, ticker),
            layer=layer,
            layer_zh=LAYER_ZH[layer],
            layer_en=LAYER_EN[layer],
            layer_color=LAYER_COLOR[layer],
            days_in_layer=days_in,
            entered_layer_date=entered,
            prior_layer=prior_layer,
            streak=acc.get("streak", 0),
            net_cumulative=acc.get("net_cumulative") or 0,
            velocity_3d=acc.get("velocity_3d"),
            acceleration=acc.get("acceleration"),
            sponsorship_score=sp.get("persistence_score", 0.0),
            top_broker=sp.get("top_persistent_broker"),
            top_broker_days=sp.get("top_broker_days", 0),
            failed_breakout=fb.get("failed_breakout_detected", False),
            sector=sm.sector_of(ticker),
            is_tier_a=ticker in TIER_A,
            velocity_turning_negative=_velocity_turning_negative(records),
            days_since_last_failure=days_since_fail,
        )

        if layer == LAYER_DISCOVERY:
            result.discovery.append(cr)
        elif layer == LAYER_OBSERVATION:
            result.observation.append(cr)
        elif layer == LAYER_CONFIRMATION:
            result.confirmation.append(cr)
        elif layer == LAYER_RISK_WARNING:
            result.risk_warning.append(cr)
        elif layer == LAYER_FAILURE:
            result.failure.append(cr)

    # Sort each layer
    def _sort_key(r: CandidateRecord) -> tuple:
        return (-r.streak, -(r.net_cumulative or 0), -r.sponsorship_score)

    result.discovery.sort(key=_sort_key)
    result.observation.sort(key=_sort_key)
    result.confirmation.sort(key=_sort_key)
    result.risk_warning.sort(key=lambda r: -(r.days_in_layer))
    result.failure.sort(key=lambda r: -(r.days_in_layer))

    return result


def funnel_layer(ticker: str, snapshots: list[dict]) -> str:
    """Return the funnel layer string for a single ticker. Fast path."""
    if not snapshots:
        return LAYER_UNDISCOVERED
    sm = build_sector_map(snapshots)
    rh = _build_sector_rank_history(snapshots, sm)
    return _assign_layer_single(ticker, snapshots, rh, sm)


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

    p = argparse.ArgumentParser(description="SCD Candidate Funnel Engine")
    p.add_argument("--json",  action="store_true")
    p.add_argument("--layer", choices=["discovery","observation","confirmation","risk_warning","failure","all"],
                   default="all")
    args = p.parse_args()

    fr = run(snaps)

    if args.json:
        print(_json.dumps(fr.as_dict(), ensure_ascii=False, indent=2, default=str))
        import sys; sys.exit(0)

    W = 66
    print(f"\n{'═'*W}")
    print(f"  候選漏斗引擎  CANDIDATE FUNNEL  {fr.date}  ({fr.snapshot_count} snapshots)")
    print(f"{'═'*W}")
    print(f"  Discovery={len(fr.discovery)}  Observation={len(fr.observation)}  "
          f"Confirmation={len(fr.confirmation)}  "
          f"RiskWarning={len(fr.risk_warning)}  Failure={len(fr.failure)}")

    def _print_layer(records: list[CandidateRecord], title: str) -> None:
        if not records:
            return
        print(f"\n── {title} ({len(records)}) {'─'*(W-len(title)-7)}")
        for r in records:
            tier  = "[A] " if r.is_tier_a else "    "
            price_info = ""
            chg   = f"+{r.velocity_3d:,.0f}/日" if r.velocity_3d and r.velocity_3d > 0 else \
                    (f"{r.velocity_3d:,.0f}/日" if r.velocity_3d else "")
            prior = f" ← {LAYER_ZH.get(r.prior_layer,'')}" if r.prior_layer else ""
            print(f"  {tier}{r.ticker} {r.name:<10}  連買{r.streak}日  "
                  f"累計{r.net_cumulative:+,}張  {chg:<12}  "
                  f"贊助{r.sponsorship_score:.2f}  {r.days_in_layer}日{prior}")

    layers_to_show = (
        ["discovery","observation","confirmation","risk_warning","failure"]
        if args.layer == "all" else [args.layer]
    )
    layer_map = {
        "discovery":    (fr.discovery,    f"Layer 1  發現 Discovery"),
        "observation":  (fr.observation,  f"Layer 2  觀察 Observation"),
        "confirmation": (fr.confirmation, f"Layer 3  確認 Confirmation"),
        "risk_warning": (fr.risk_warning, f"Layer 4  風險 Risk Warning"),
        "failure":      (fr.failure,      f"Layer 5  失敗 Failure"),
    }
    for lk in layers_to_show:
        records, title = layer_map[lk]
        _print_layer(records, title)
    print()
