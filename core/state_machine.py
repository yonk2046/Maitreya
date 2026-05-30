"""SCD Engine — Temporal State Machine  (STEP 6)
時序狀態機

Tracks each ticker's lifecycle state across snapshot history.
Fully deterministic: same snapshot inputs → same state output, always.
No stored state. No side effects. Pure function.

States (ordered by lifecycle stage)
─────────────────────────────────────
  UNDISCOVERED  → not yet in universe
  DISCOVERED    → appeared ≥1 time, minimal signal
  ACCUMULATING  → streak ≥ 1, mfb > 0
  STRENGTHENING → streak ≥ 3, sponsorship ≥ 0.4
  DISTRIBUTING  → was STRENGTHENING/CONFIRMED, now velocity turning negative
                  (early warning — not yet failed)
  CONFIRMED     → streak ≥ 3, sponsorship ≥ 0.5, sector top-5 (relative),
                  no failed breakout, breadth ≥ 50%
  EXTENDED      → CONFIRMED but velocity slowing + price extended from cost
  FAILED        → failed_breakout detected OR streak collapses 3→0 ≤ 2 days
  EXITED        → disappeared from universe for ≥3 consecutive snapshots

Transition risk levels
───────────────────────
  low       — state is stable, no warning signals
  medium    — one minor deterioration signal
  elevated  — multiple signals or approaching known risk threshold
  critical  — in DISTRIBUTING/EXTENDED or recent FAILED history

Public API
──────────
  compute(ticker, snapshots)          → TickerState
  run_all(snapshots)                  → dict[ticker, TickerState]
  state_summary(snapshots)            → MarketStateSummary
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

from core.market_context import (
    accumulation_velocity,
    sponsorship_persistence,
    failed_breakout_memory,
    regime_shift,
)
from core.sector_intelligence import (
    build_sector_map,
    _collect_per_snap,
)
from core.watchlists import TIER_A, build_name_map

# ── Thresholds ────────────────────────────────────────────────────────────────
STREAK_ACCUMULATING   = 1
STREAK_STRENGTHENING  = 3
STREAK_CONFIRMED      = 3
SPON_STRENGTHENING    = 0.40
SPON_CONFIRMED        = 0.50
SECTOR_TOP_N_CONFIRM  = 5      # sector must be in top-N for CONFIRMED
BREADTH_CONFIRMED     = 0.50   # market breadth required for CONFIRMED
ABSENT_EXITED         = 3      # consecutive absent snapshots → EXITED
COLLAPSE_WINDOW       = 2      # streak 3→0 within this many days → FAILED
DAYS_SINCE_FAIL_RISK  = 10     # failed breakout within this many days → elevated risk

# ── State keys ────────────────────────────────────────────────────────────────
S_UNDISCOVERED  = "undiscovered"
S_DISCOVERED    = "discovered"
S_ACCUMULATING  = "accumulating"
S_STRENGTHENING = "strengthening"
S_DISTRIBUTING  = "distributing"
S_CONFIRMED     = "confirmed"
S_EXTENDED      = "extended"
S_FAILED        = "failed"
S_EXITED        = "exited"

STATE_ORDER = [
    S_UNDISCOVERED, S_DISCOVERED, S_ACCUMULATING, S_STRENGTHENING,
    S_DISTRIBUTING, S_CONFIRMED, S_EXTENDED, S_FAILED, S_EXITED,
]

STATE_ZH = {
    S_UNDISCOVERED:  "未追蹤",
    S_DISCOVERED:    "初現",
    S_ACCUMULATING:  "吸籌中",
    S_STRENGTHENING: "轉強",
    S_DISTRIBUTING:  "疑似出貨",
    S_CONFIRMED:     "成熟確認",
    S_EXTENDED:      "過熱延伸",
    S_FAILED:        "結構失敗",
    S_EXITED:        "已退出",
}

STATE_EN = {
    S_UNDISCOVERED:  "Undiscovered",
    S_DISCOVERED:    "Discovered",
    S_ACCUMULATING:  "Accumulating",
    S_STRENGTHENING: "Strengthening",
    S_DISTRIBUTING:  "Distributing",
    S_CONFIRMED:     "Confirmed",
    S_EXTENDED:      "Extended",
    S_FAILED:        "Failed Structure",
    S_EXITED:        "Exited",
}

STATE_COLOR = {
    S_UNDISCOVERED:  "#1E2A36",
    S_DISCOVERED:    "#3A5060",
    S_ACCUMULATING:  "#4A8A6A",
    S_STRENGTHENING: "#52B788",
    S_DISTRIBUTING:  "#D4A84B",
    S_CONFIRMED:     "#7EB8D4",
    S_EXTENDED:      "#C47A5A",
    S_FAILED:        "#E05C7A",
    S_EXITED:        "#2A3040",
}

RISK_LEVELS = ("low", "medium", "elevated", "critical")

RISK_ZH = {
    "low":      "低風險",
    "medium":   "中度風險",
    "elevated": "風險偏高",
    "critical": "高風險",
}

RISK_EN = {
    "low":      "Low Risk",
    "medium":   "Medium Risk",
    "elevated": "Elevated Risk",
    "critical": "Critical Risk",
}

RISK_COLOR = {
    "low":      "#52B788",
    "medium":   "#7EB8D4",
    "elevated": "#D4A84B",
    "critical": "#E05C7A",
}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class StateTransition:
    """One recorded state change."""
    date:       str
    from_state: str
    to_state:   str
    trigger:    str   # short reason string


@dataclass
class TickerState:
    ticker:          str
    name:            str
    state:           str
    state_zh:        str
    state_en:        str
    state_color:     str
    days_in_state:   int
    state_entered:   str | None        # date of entry into current state
    state_history:   list[str]         # ordered list of states (oldest→latest, deduped)
    # Transition risk (non-default fields must precede defaults)
    transition_risk:       str   # low / medium / elevated / critical
    transition_risk_zh:    str
    transition_risk_en:    str
    transition_risk_color: str

    transitions:     list[StateTransition] = field(default_factory=list)
    risk_factors:    list[str]             = field(default_factory=list)

    # Latest metrics snapshot
    streak:            int   = 0
    net_cumulative:    int   = 0
    velocity_3d:       float | None = None
    acceleration:      float | None = None
    sponsorship_score: float = 0.0
    failed_breakout:   bool  = False
    sector:            str   = "other"
    is_tier_a:         bool  = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker":           self.ticker,
            "name":             self.name,
            "state":            self.state,
            "state_zh":         self.state_zh,
            "state_en":         self.state_en,
            "state_color":      self.state_color,
            "days_in_state":    self.days_in_state,
            "state_entered":    self.state_entered,
            "state_history":    self.state_history,
            "transitions":      [
                {"date": t.date, "from": t.from_state,
                 "to": t.to_state, "trigger": t.trigger}
                for t in self.transitions
            ],
            "transition_risk":       self.transition_risk,
            "transition_risk_zh":    self.transition_risk_zh,
            "transition_risk_en":    self.transition_risk_en,
            "transition_risk_color": self.transition_risk_color,
            "risk_factors":          self.risk_factors,
            "streak":            self.streak,
            "net_cumulative":    self.net_cumulative,
            "velocity_3d":       self.velocity_3d,
            "acceleration":      self.acceleration,
            "sponsorship_score": self.sponsorship_score,
            "failed_breakout":   self.failed_breakout,
            "sector":            self.sector,
            "is_tier_a":         self.is_tier_a,
        }


@dataclass
class MarketStateSummary:
    date:          str
    snapshot_count: int
    state_counts:  dict[str, int]   # state → count
    # Notable clusters
    confirmed:     list[TickerState]
    strengthening: list[TickerState]
    distributing:  list[TickerState]
    failed:        list[TickerState]
    # Transitions today
    new_entries:   list[TickerState]   # moved to higher state today
    new_failures:  list[TickerState]   # entered FAILED/DISTRIBUTING today

    def as_dict(self) -> dict[str, Any]:
        return {
            "date":           self.date,
            "snapshot_count": self.snapshot_count,
            "state_counts":   self.state_counts,
            "confirmed":      [t.as_dict() for t in self.confirmed],
            "strengthening":  [t.as_dict() for t in self.strengthening],
            "distributing":   [t.as_dict() for t in self.distributing],
            "failed":         [t.as_dict() for t in self.failed],
            "new_entries":    [t.as_dict() for t in self.new_entries],
            "new_failures":   [t.as_dict() for t in self.new_failures],
        }


# ── Sector rank history helper ────────────────────────────────────────────────

def _sector_rank_per_snap(snapshots: list[dict], sm=None) -> list[list[str]]:
    """Returns ordered sector lists per snapshot (oldest→latest)."""
    if sm is None:
        sm = build_sector_map(snapshots)
    per = _collect_per_snap(snapshots, sm)
    out: list[list[str]] = []
    for ps in per:
        ranked = sorted(
            ps["sector_data"].keys(),
            key=lambda s: -sum(ps["sector_data"][s].get("mfb_vals", []) or [0]),
        )
        out.append(ranked)
    return out


def _sector_in_top_n_relative(
    sector: str,
    rank_history: list[list[str]],
    top_n: int = SECTOR_TOP_N_CONFIRM,
    window: int = 3,
    min_hits: int = 2,
) -> bool:
    """True if sector appears in top_n on ≥ min_hits of last <window> days."""
    recent = rank_history[-window:]
    hits = sum(1 for day in recent if sector in day[:top_n])
    return hits >= min_hits


# ── State assignment ──────────────────────────────────────────────────────────

def _assign_state(
    ticker: str,
    records: list[dict],           # chronological, this ticker only
    snapshot_dates: list[str],     # all dates in window
    rank_history: list[list[str]], # sector rank per snap
    breadth_series: list[float],   # market breadth per snap
    sm=None,
) -> str:
    """
    Assign the current state for one ticker.
    All inputs must be pre-computed for performance.
    """
    if not records:
        # Check if recently exited
        return S_UNDISCOVERED

    appearances = len(records)
    record_dates = {r.get("date", "") for r in records}

    # Check EXITED: last ABSENT_EXITED snapshot dates all missing
    tail_dates = snapshot_dates[-ABSENT_EXITED:]
    if len(tail_dates) >= ABSENT_EXITED and not (record_dates & set(tail_dates)):
        return S_EXITED

    # Basic metrics
    mfb_vals = [r.get("main_force_buy") for r in records if r.get("main_force_buy") is not None]
    if not mfb_vals:
        return S_DISCOVERED

    acc  = accumulation_velocity(ticker, records)
    sp   = sponsorship_persistence(ticker, records)
    fb   = failed_breakout_memory(ticker, records)
    sector = sm.sector_of(ticker) if sm else "other"

    streak  = acc["streak"]
    spon    = sp["persistence_score"]
    vel     = acc.get("velocity_3d")
    accel   = acc.get("acceleration")
    failed  = fb["failed_breakout_detected"]

    # ── FAILED ────────────────────────────────────────────────────────────
    if failed:
        return S_FAILED

    # Streak collapse: was ≥3, now 0 within COLLAPSE_WINDOW snapshots
    if streak == 0 and appearances >= COLLAPSE_WINDOW + 1:
        recent_mfb = [r.get("main_force_buy") or 0
                      for r in records[-(COLLAPSE_WINDOW + 1):-1]]
        if any(v > 0 for v in recent_mfb):
            prior_streak = sum(1 for v in recent_mfb if v > 0)
            if prior_streak >= COLLAPSE_WINDOW:
                return S_FAILED

    # ── DISTRIBUTING ──────────────────────────────────────────────────────
    # Was in STRENGTHENING territory but velocity now turning negative
    was_strong = (
        sum(1 for r in records[-5:] if (r.get("main_force_buy") or 0) > 0) >= 3
    )
    vel_negative = vel is not None and vel < 0
    accel_negative = accel is not None and accel < -500
    if was_strong and streak >= 1 and (vel_negative or accel_negative):
        return S_DISTRIBUTING

    # ── CONFIRMED ─────────────────────────────────────────────────────────
    sector_strong = _sector_in_top_n_relative(sector, rank_history)
    latest_breadth = breadth_series[-1] if breadth_series else 0.0
    if (streak >= STREAK_CONFIRMED
            and spon >= SPON_CONFIRMED
            and sector_strong
            and not failed
            and latest_breadth >= BREADTH_CONFIRMED):
        # Check EXTENDED: velocity decelerating after confirmed
        if accel is not None and accel < 0 and vel is not None and vel > 0:
            return S_EXTENDED
        return S_CONFIRMED

    # ── STRENGTHENING ─────────────────────────────────────────────────────
    if streak >= STREAK_STRENGTHENING and spon >= SPON_STRENGTHENING:
        return S_STRENGTHENING

    # ── ACCUMULATING ──────────────────────────────────────────────────────
    if streak >= STREAK_ACCUMULATING and mfb_vals and mfb_vals[-1] > 0:
        return S_ACCUMULATING

    # ── DISCOVERED ────────────────────────────────────────────────────────
    return S_DISCOVERED


# ── Transition risk computation ───────────────────────────────────────────────

def _compute_risk(
    state: str,
    acc:   dict,
    sp:    dict,
    fb:    dict,
    records: list[dict],
    snapshot_dates: list[str],
) -> tuple[str, list[str]]:
    """
    Compute transition_risk level and list of risk_factors.
    Returns (risk_level, [factor_strings])
    """
    factors: list[str] = []
    score = 0   # 0=low, accumulate to classify

    # Critical conditions
    if state in (S_FAILED, S_DISTRIBUTING):
        score += 3
        factors.append(f"狀態本身為 {STATE_ZH[state]}")

    if state == S_EXTENDED:
        score += 2
        factors.append("價格延伸／動能減速")

    # Recent failed breakout proximity
    fb_date = fb.get("breakout_date")
    if fb_date and fb_date in snapshot_dates:
        days_ago = len(snapshot_dates) - 1 - snapshot_dates.index(fb_date)
        if days_ago <= DAYS_SINCE_FAIL_RISK:
            score += 2
            factors.append(f"假突破紀錄 {days_ago} 日前")

    # Velocity turning negative
    vel = acc.get("velocity_3d")
    if vel is not None and vel < 0:
        score += 1
        factors.append("3日速度為負")

    # Acceleration strongly negative
    accel = acc.get("acceleration")
    if accel is not None and accel < -1000:
        score += 1
        factors.append(f"加速度 {accel:,.0f}")

    # Low sponsorship in otherwise positive state
    spon = sp.get("persistence_score", 0)
    if state in (S_STRENGTHENING, S_CONFIRMED) and spon < 0.4:
        score += 1
        factors.append(f"贊助分偏低 {spon:.2f}")

    # Classify
    if score >= 4:
        level = "critical"
    elif score >= 2:
        level = "elevated"
    elif score >= 1:
        level = "medium"
    else:
        level = "low"

    return level, factors


# ── State history reconstruction ──────────────────────────────────────────────

def _build_state_history(
    ticker: str,
    snapshots: list[dict],
    rank_history: list[list[str]],
    breadth_series: list[float],
    sm=None,
) -> tuple[list[str], list[StateTransition]]:
    """
    Walk each snapshot window and record state sequence + transitions.
    Returns (state_history_deduped, transitions).
    """
    state_seq: list[tuple[str, str]] = []  # (date, state)

    for i in range(1, len(snapshots) + 1):
        sub      = snapshots[:i]
        srh      = rank_history[:i]
        sbs      = breadth_series[:i]
        s_dates  = [s.get("date", "") for s in sub]
        records  = [
            {**s_rec, "date": snap.get("date", "")}
            for snap in sub
            for s_rec in snap.get("stocks", [])
            if s_rec.get("ticker") == ticker
        ]
        state = _assign_state(ticker, records, s_dates, srh, sbs, sm)
        date  = snapshots[i - 1].get("date", "")
        state_seq.append((date, state))

    # Dedup history
    history: list[str] = []
    transitions: list[StateTransition] = []
    prev_state: str | None = None

    for date, state in state_seq:
        if state != prev_state:
            if prev_state is not None:
                transitions.append(StateTransition(
                    date=date,
                    from_state=prev_state,
                    to_state=state,
                    trigger=_transition_trigger(prev_state, state),
                ))
            if not history or history[-1] != state:
                history.append(state)
            prev_state = state

    return history, transitions


def _transition_trigger(from_s: str, to_s: str) -> str:
    mapping = {
        (S_UNDISCOVERED, S_DISCOVERED):    "首次出現",
        (S_DISCOVERED,   S_ACCUMULATING):  "主力開始買超",
        (S_ACCUMULATING, S_STRENGTHENING): "連買≥3日+贊助確立",
        (S_STRENGTHENING,S_CONFIRMED):     "族群+廣度+贊助三重確認",
        (S_CONFIRMED,    S_EXTENDED):      "動能減速",
        (S_STRENGTHENING,S_DISTRIBUTING):  "速度轉負，疑似出貨",
        (S_CONFIRMED,    S_DISTRIBUTING):  "速度轉負，疑似出貨",
        (S_DISTRIBUTING, S_FAILED):        "假突破/完全出場",
        (S_EXTENDED,     S_FAILED):        "結構崩壞",
        (S_FAILED,       S_DISCOVERED):    "重新進場",
        (S_FAILED,       S_ACCUMULATING):  "重新累積",
    }
    return mapping.get((from_s, to_s), f"{STATE_ZH.get(from_s,'?')}→{STATE_ZH.get(to_s,'?')}")


# ── Days in current state ─────────────────────────────────────────────────────

def _days_and_entry(
    transitions: list[StateTransition],
    current_state: str,
    snapshot_dates: list[str],
) -> tuple[int, str | None]:
    """
    Find entry date of current state from transition list.
    Falls back to counting from end if no transition recorded.
    """
    # Find last transition INTO current state
    for t in reversed(transitions):
        if t.to_state == current_state:
            # Count snapshots from that date
            if t.date in snapshot_dates:
                idx = snapshot_dates.index(t.date)
                return len(snapshot_dates) - idx, t.date
            break
    # Fallback: state has been current for all known snapshots
    return len(snapshot_dates), snapshot_dates[0] if snapshot_dates else None


# ── Public API ────────────────────────────────────────────────────────────────

def compute(ticker: str, snapshots: list[dict]) -> TickerState:
    """Compute the full TickerState for one ticker across all snapshots."""
    if not snapshots:
        return _empty_ticker_state(ticker, "")

    name_map    = build_name_map(snapshots)
    sm          = build_sector_map(snapshots)
    rh          = _sector_rank_per_snap(snapshots, sm)
    reg         = regime_shift(snapshots)
    breadth_s   = reg.get("breadth_series", [0.0] * len(snapshots))
    snap_dates  = [s.get("date", "") for s in snapshots]

    # Build records
    records = [
        {**rec, "date": snap.get("date", "")}
        for snap in snapshots
        for rec in snap.get("stocks", [])
        if rec.get("ticker") == ticker
    ]

    # Current state
    state = _assign_state(ticker, records, snap_dates, rh, breadth_s, sm)

    # Full history + transitions
    history, transitions = _build_state_history(ticker, snapshots, rh, breadth_s, sm)

    # Days in state
    days_in, entered = _days_and_entry(transitions, state, snap_dates)

    # Metrics
    mfb_vals = [r.get("main_force_buy") for r in records if r.get("main_force_buy") is not None]
    acc  = accumulation_velocity(ticker, records) if mfb_vals else {}
    sp   = sponsorship_persistence(ticker, records)
    fb   = failed_breakout_memory(ticker, records)

    # Risk
    risk_level, risk_factors = _compute_risk(state, acc, sp, fb, records, snap_dates)

    return TickerState(
        ticker=ticker,
        name=name_map.get(ticker, ticker),
        state=state,
        state_zh=STATE_ZH[state],
        state_en=STATE_EN[state],
        state_color=STATE_COLOR[state],
        days_in_state=days_in,
        state_entered=entered,
        state_history=history,
        transitions=transitions,
        transition_risk=risk_level,
        transition_risk_zh=RISK_ZH[risk_level],
        transition_risk_en=RISK_EN[risk_level],
        transition_risk_color=RISK_COLOR[risk_level],
        risk_factors=risk_factors,
        streak=acc.get("streak", 0),
        net_cumulative=acc.get("net_cumulative") or 0,
        velocity_3d=acc.get("velocity_3d"),
        acceleration=acc.get("acceleration"),
        sponsorship_score=sp.get("persistence_score", 0.0),
        failed_breakout=fb.get("failed_breakout_detected", False),
        sector=sm.sector_of(ticker),
        is_tier_a=ticker in TIER_A,
    )


def run_all(snapshots: list[dict]) -> dict[str, TickerState]:
    """
    Compute TickerState for every ticker seen across all snapshots.
    Returns {ticker: TickerState}.
    """
    if not snapshots:
        return {}

    sm         = build_sector_map(snapshots)
    rh         = _sector_rank_per_snap(snapshots, sm)
    reg        = regime_shift(snapshots)
    breadth_s  = reg.get("breadth_series", [0.0] * len(snapshots))
    snap_dates = [s.get("date", "") for s in snapshots]
    name_map   = build_name_map(snapshots)

    all_tickers: set[str] = set()
    for snap in snapshots:
        for s in snap.get("stocks", []):
            t = s.get("ticker", "")
            if t:
                all_tickers.add(t)

    result: dict[str, TickerState] = {}

    for ticker in sorted(all_tickers):
        records = [
            {**rec, "date": snap.get("date", "")}
            for snap in snapshots
            for rec in snap.get("stocks", [])
            if rec.get("ticker") == ticker
        ]

        state = _assign_state(ticker, records, snap_dates, rh, breadth_s, sm)
        history, transitions = _build_state_history(ticker, snapshots, rh, breadth_s, sm)
        days_in, entered = _days_and_entry(transitions, state, snap_dates)

        mfb_vals = [r.get("main_force_buy") for r in records if r.get("main_force_buy") is not None]
        acc  = accumulation_velocity(ticker, records) if mfb_vals else {}
        sp   = sponsorship_persistence(ticker, records)
        fb   = failed_breakout_memory(ticker, records)
        risk_level, risk_factors = _compute_risk(state, acc, sp, fb, records, snap_dates)

        result[ticker] = TickerState(
            ticker=ticker,
            name=name_map.get(ticker, ticker),
            state=state,
            state_zh=STATE_ZH[state],
            state_en=STATE_EN[state],
            state_color=STATE_COLOR[state],
            days_in_state=days_in,
            state_entered=entered,
            state_history=history,
            transitions=transitions,
            transition_risk=risk_level,
            transition_risk_zh=RISK_ZH[risk_level],
            transition_risk_en=RISK_EN[risk_level],
            transition_risk_color=RISK_COLOR[risk_level],
            risk_factors=risk_factors,
            streak=acc.get("streak", 0),
            net_cumulative=acc.get("net_cumulative") or 0,
            velocity_3d=acc.get("velocity_3d"),
            acceleration=acc.get("acceleration"),
            sponsorship_score=sp.get("persistence_score", 0.0),
            failed_breakout=fb.get("failed_breakout_detected", False),
            sector=sm.sector_of(ticker),
            is_tier_a=ticker in TIER_A,
        )

    return result


def state_summary(snapshots: list[dict]) -> MarketStateSummary:
    """
    Run all tickers and return a MarketStateSummary with notable clusters.
    """
    if not snapshots:
        return MarketStateSummary(
            date="—", snapshot_count=0,
            state_counts={s: 0 for s in STATE_ORDER},
            confirmed=[], strengthening=[], distributing=[],
            failed=[], new_entries=[], new_failures=[],
        )

    all_states = run_all(snapshots)
    date = snapshots[-1].get("date", "?")

    # State counts
    counts: dict[str, int] = {s: 0 for s in STATE_ORDER}
    for ts in all_states.values():
        counts[ts.state] = counts.get(ts.state, 0) + 1

    def _by_state(s: str) -> list[TickerState]:
        return sorted(
            [ts for ts in all_states.values() if ts.state == s],
            key=lambda t: (-t.streak, -(t.net_cumulative or 0)),
        )

    # New transitions today (last snapshot)
    prev_snaps = snapshots[:-1]
    new_entries: list[TickerState] = []
    new_failures: list[TickerState] = []

    if prev_snaps:
        prev_states = run_all(prev_snaps)
        for ticker, ts in all_states.items():
            prev = prev_states.get(ticker)
            if prev is None:
                continue
            prev_rank = STATE_ORDER.index(prev.state) if prev.state in STATE_ORDER else 0
            curr_rank = STATE_ORDER.index(ts.state) if ts.state in STATE_ORDER else 0
            if curr_rank > prev_rank and ts.state not in (S_FAILED, S_EXITED, S_DISTRIBUTING):
                new_entries.append(ts)
            if ts.state in (S_FAILED, S_DISTRIBUTING) and prev.state not in (S_FAILED, S_DISTRIBUTING):
                new_failures.append(ts)

    return MarketStateSummary(
        date=date,
        snapshot_count=len(snapshots),
        state_counts=counts,
        confirmed=_by_state(S_CONFIRMED),
        strengthening=_by_state(S_STRENGTHENING),
        distributing=_by_state(S_DISTRIBUTING),
        failed=_by_state(S_FAILED),
        new_entries=new_entries,
        new_failures=new_failures,
    )


def _empty_ticker_state(ticker: str, date: str) -> TickerState:
    return TickerState(
        ticker=ticker, name=ticker,
        state=S_UNDISCOVERED, state_zh=STATE_ZH[S_UNDISCOVERED],
        state_en=STATE_EN[S_UNDISCOVERED], state_color=STATE_COLOR[S_UNDISCOVERED],
        days_in_state=0, state_entered=None, state_history=[],
        transitions=[], transition_risk="low",
        transition_risk_zh=RISK_ZH["low"], transition_risk_en=RISK_EN["low"],
        transition_risk_color=RISK_COLOR["low"], risk_factors=[],
    )


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

    p = argparse.ArgumentParser(description="SCD Temporal State Machine")
    p.add_argument("--json",   action="store_true")
    p.add_argument("--ticker", default=None, help="Single ticker to inspect")
    args = p.parse_args()

    if args.ticker:
        ts = compute(args.ticker, snaps)
        if args.json:
            print(_json.dumps(ts.as_dict(), ensure_ascii=False, indent=2, default=str))
        else:
            W = 64
            print(f"\n{'═'*W}")
            print(f"  {ts.ticker} {ts.name}  狀態: {ts.state_zh} / {ts.state_en}")
            print(f"{'═'*W}")
            print(f"  在此狀態 {ts.days_in_state} 日  (進入 {ts.state_entered})")
            print(f"  狀態歷程: {' → '.join(STATE_ZH.get(s, s) for s in ts.state_history)}")
            print(f"  風險等級: {ts.transition_risk_zh} / {ts.transition_risk_en}")
            if ts.risk_factors:
                print(f"  風險因素: {', '.join(ts.risk_factors)}")
            print(f"  連買 {ts.streak}日  累計 {ts.net_cumulative:+,}張  贊助 {ts.sponsorship_score:.2f}")
            print(f"  近期轉換:")
            for tr in ts.transitions[-5:]:
                print(f"    {tr.date}  {STATE_ZH.get(tr.from_state,'?')} → {STATE_ZH.get(tr.to_state,'?')}  ({tr.trigger})")
        import sys; sys.exit(0)

    summary = state_summary(snaps)

    if args.json:
        print(_json.dumps(summary.as_dict(), ensure_ascii=False, indent=2, default=str))
        import sys; sys.exit(0)

    W = 68
    print(f"\n{'═'*W}")
    print(f"  時序狀態機  TEMPORAL STATE MACHINE  {summary.date}  ({summary.snapshot_count} snaps)")
    print(f"{'═'*W}")
    print("  狀態分布 State Distribution:")
    for s in STATE_ORDER:
        n = summary.state_counts.get(s, 0)
        if n:
            bar = "▪" * n
            print(f"    {STATE_ZH[s]:8s} {n:3d}  {bar}")

    def _print_cluster(tickers: list[TickerState], title: str, n: int = 8) -> None:
        if not tickers:
            return
        print(f"\n── {title} ({len(tickers)}) {'─'*(W-len(title)-7)}")
        for ts in tickers[:n]:
            risk_sym = {"low": "○", "medium": "◑", "elevated": "●", "critical": "⚠"}
            tier = "[A]" if ts.is_tier_a else "   "
            print(f"  {risk_sym.get(ts.transition_risk,'?')} {tier} {ts.ticker} {ts.name:<10}  "
                  f"{ts.state_zh:<8}  連買{ts.streak}日  "
                  f"累計{ts.net_cumulative:+,}張  贊助{ts.sponsorship_score:.2f}  "
                  f"{ts.days_in_state}日")

    _print_cluster(summary.confirmed,     "成熟確認 Confirmed")
    _print_cluster(summary.strengthening, "轉強 Strengthening")
    _print_cluster(summary.distributing,  "疑似出貨 Distributing")
    _print_cluster(summary.failed,        "結構失敗 Failed")

    if summary.new_entries:
        _print_cluster(summary.new_entries,  "今日晉升 Promoted Today")
    if summary.new_failures:
        _print_cluster(summary.new_failures, "今日警示 New Warnings Today")
    print()
