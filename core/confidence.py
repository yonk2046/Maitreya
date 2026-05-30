"""SCD Engine — Confidence & Risk Profile  (STEP 8)
信心度與風險側寫

Synthesises three upstream modules into a two-dimensional per-ticker reading:

  Confidence  (0.0 – 1.0)  How much evidence supports the current condition
  Risk Score  (0.0 – 1.0)  How much warning evidence is present

Together they form a 2-D profile, e.g.:
  HIGH confidence + LOW risk   → strongest observable structure
  HIGH confidence + ELEVATED   → watch carefully — strength but cracks forming
  LOW  confidence + HIGH risk  → structure eroding

Also produces a MarketRiskTemperature (0.0–1.0) — the aggregate market-level
risk reading derived from the distribution of profiles across the universe.

Pure observation. No buy/sell signals. Deterministic.

────────────────────────────────────────────────────────────────────────
Confidence score components (additive, capped at 1.0)
────────────────────────────────────────────────────────────────────────
  streak_component       streak / STREAK_SCALE  capped at STREAK_CAP  (max 0.30)
  sponsorship_component  sponsorship * SPON_WEIGHT                     (max 0.25)
  velocity_positive      +CONF_VEL_POS  if velocity_3d > 0             (+0.15)
  acceleration_positive  +CONF_ACCEL    if acceleration > 0             (+0.10)
  in_golden_layer        +CONF_GOLDEN   if in Golden Layer              (+0.15)
  golden_conviction_add  golden_conviction * CONF_CONVICTION_SCALE      (max 0.05)
  sector_strong_add      +CONF_SECTOR   if sector in top-3              (+0.05)
  tier_a_add             +CONF_TIER_A   if Tier A ticker                (+0.05)

────────────────────────────────────────────────────────────────────────
Risk score components (additive, capped at 1.0)
────────────────────────────────────────────────────────────────────────
  sm_base_risk       critical→0.40  elevated→0.25  medium→0.10  low→0.0
  distributing       +RISK_DISTRIBUTING  if state == DISTRIBUTING        (+0.25)
  funnel_warning     +RISK_FUNNEL_WARN   if funnel layer == risk_warning (+0.20)
  failed_breakout    +RISK_FB            if failed_breakout recent        (+0.20)
  velocity_negative  +RISK_VEL_NEG       if velocity_3d < 0              (+0.15)
  accel_strongly_neg +RISK_ACCEL_NEG     if acceleration < -500          (+0.10)
  streak_zero        +RISK_NO_STREAK     if streak == 0                  (+0.10)

risk_score → risk_level:
  ≥ 0.50 → critical   ≥ 0.30 → elevated   ≥ 0.15 → medium   else → low

────────────────────────────────────────────────────────────────────────
Profile codes  (confidence_band × risk_band)
────────────────────────────────────────────────────────────────────────
  high_low      confidence ≥ 0.55 AND risk ≤ 0.15  → ideal observable structure
  high_medium   confidence ≥ 0.55 AND risk 0.15–0.30
  high_elevated confidence ≥ 0.55 AND risk ≥ 0.30  → strength with warning
  mid_low       confidence 0.30–0.55 AND risk ≤ 0.15
  mid_elevated  confidence 0.30–0.55 AND risk ≥ 0.30
  low_any       confidence < 0.30                  → insufficient signal
  deteriorating confidence falling AND risk rising simultaneously

────────────────────────────────────────────────────────────────────────
Market Risk Temperature  (0.0 – 1.0)
────────────────────────────────────────────────────────────────────────
  Component weights:
    elevated_risk_ratio    40%  — fraction of tracked tickers with elevated/critical risk
    distributing_ratio     30%  — (distributing) / (confirmed + strengthening + distributing)
    breadth_deterioration  30%  — breadth trend declining

  Levels:
    ≥ 0.70 → 極端  Extreme   ≥ 0.50 → 過熱  Hot
    ≥ 0.35 → 偏熱  Warm      ≥ 0.20 → 穩定  Stable    < 0.20 → 冷靜  Cool

────────────────────────────────────────────────────────────────────────
Public API
────────────────────────────────────────────────────────────────────────
  run(snapshots)                              → ConfidenceResult
  ticker_profile(ticker, snapshots)           → ConfidenceProfile | None
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

from core.golden        import run as golden_run, GoldenResult, GoldenEntry
from core.golden        import TIER_PRIME_KEY, TIER_STRONG_KEY
from core.state_machine import (
    run_all as sm_run_all,
    state_summary as sm_state_summary,
    S_CONFIRMED, S_STRENGTHENING, S_DISTRIBUTING, S_FAILED,
)
from core.funnel        import LAYER_RISK_WARNING, LAYER_CONFIRMATION
from core.market_context import regime_shift
from core.watchlists    import TIER_A

# ── Confidence score weights ──────────────────────────────────────────────────
STREAK_SCALE             = 10.0    # streak / this → contribution
STREAK_CAP               = 0.30    # max from streak
SPON_WEIGHT              = 0.25    # sponsorship * this
CONF_VEL_POS             = 0.15
CONF_ACCEL               = 0.10
CONF_GOLDEN              = 0.15
CONF_CONVICTION_SCALE    = 0.05    # golden_conviction * this (max 0.05 since conviction ≤ 1)
CONF_SECTOR              = 0.05
CONF_TIER_A              = 0.05

# ── Risk score weights ────────────────────────────────────────────────────────
RISK_SM_BASE   = {"critical": 0.40, "elevated": 0.25, "medium": 0.10, "low": 0.0}
RISK_DISTRIBUTING  = 0.25
RISK_FUNNEL_WARN   = 0.20
RISK_FB            = 0.20
RISK_VEL_NEG       = 0.15
RISK_ACCEL_NEG     = 0.10
RISK_NO_STREAK     = 0.10

# ── Profile thresholds ────────────────────────────────────────────────────────
CONF_HIGH  = 0.55
CONF_MID   = 0.30
RISK_LOW   = 0.15
RISK_MED   = 0.30

# ── Temperature weights ───────────────────────────────────────────────────────
TEMP_W_RISK_RATIO    = 0.40
TEMP_W_DISTRIB       = 0.30
TEMP_W_BREADTH       = 0.30

# ── Labels ────────────────────────────────────────────────────────────────────
CONF_BANDS = {
    "high":   (CONF_HIGH,  1.01),
    "mid":    (CONF_MID,   CONF_HIGH),
    "low":    (0.0,        CONF_MID),
}

CONF_ZH = {
    "high": "信心高",
    "mid":  "信心中",
    "low":  "信心低",
}

CONF_COLOR = {
    "high": "#52B788",
    "mid":  "#7EB8D4",
    "low":  "#4A6A80",
}

RISK_LEVEL_ZH = {
    "critical": "極高風險",
    "elevated": "風險偏高",
    "medium":   "中度風險",
    "low":      "風險低",
}

RISK_COLOR = {
    "critical": "#E05C7A",
    "elevated": "#D4A84B",
    "medium":   "#7EB8D4",
    "low":      "#52B788",
}

PROFILE_ZH = {
    "high_low":       "強勢低風險",
    "high_medium":    "強勢中風險",
    "high_elevated":  "強勢但有警示",
    "mid_low":        "中性低風險",
    "mid_medium":     "中性中風險",
    "mid_elevated":   "中性偏高風險",
    "low_any":        "信號不足",
    "deteriorating":  "結構惡化中",
}

PROFILE_EN = {
    "high_low":       "Strong / Low Risk",
    "high_medium":    "Strong / Medium Risk",
    "high_elevated":  "Strong / Warning",
    "mid_low":        "Moderate / Low Risk",
    "mid_medium":     "Moderate / Medium Risk",
    "mid_elevated":   "Moderate / Elevated Risk",
    "low_any":        "Insufficient Signal",
    "deteriorating":  "Deteriorating",
}

PROFILE_COLOR = {
    "high_low":       "#52B788",
    "high_medium":    "#7EB8D4",
    "high_elevated":  "#D4A84B",
    "mid_low":        "#4A8A6A",
    "mid_medium":     "#6B8EAA",
    "mid_elevated":   "#C47A5A",
    "low_any":        "#3A5060",
    "deteriorating":  "#E05C7A",
}

TEMP_LEVELS = [
    (0.70, "extreme",  "極端", "#E05C7A"),
    (0.50, "hot",      "過熱", "#C47A5A"),
    (0.35, "warm",     "偏熱", "#D4A84B"),
    (0.20, "stable",   "穩定", "#7EB8D4"),
    (0.00, "cool",     "冷靜", "#52B788"),
]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ConfidenceProfile:
    # All non-default fields first
    ticker:              str
    name:                str
    confidence:          float
    confidence_band:     str    # high / mid / low
    confidence_zh:       str
    confidence_color:    str
    risk_score:          float
    risk_level:          str    # low / medium / elevated / critical
    risk_zh:             str
    risk_color:          str
    profile_code:        str    # e.g. "high_low"
    profile_zh:          str
    profile_en:          str
    profile_color:       str

    # Default fields
    confidence_factors:  list[str]          = field(default_factory=list)
    risk_factors:        list[str]          = field(default_factory=list)
    streak:              int                = 0
    velocity_3d:         float | None       = None
    acceleration:        float | None       = None
    sponsorship_score:   float              = 0.0
    sm_state:            str                = ""
    sm_state_zh:         str                = ""
    funnel_layer:        str                = ""
    in_golden:           bool               = False
    golden_tier:         str                = ""
    golden_conviction:   float              = 0.0
    sector:              str                = "other"
    is_tier_a:           bool               = False
    confidence_breakdown: dict[str, float]  = field(default_factory=dict)
    risk_breakdown:       dict[str, float]  = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker":               self.ticker,
            "name":                 self.name,
            "confidence":           round(self.confidence, 3),
            "confidence_band":      self.confidence_band,
            "confidence_zh":        self.confidence_zh,
            "confidence_color":     self.confidence_color,
            "confidence_factors":   self.confidence_factors,
            "risk_score":           round(self.risk_score, 3),
            "risk_level":           self.risk_level,
            "risk_zh":              self.risk_zh,
            "risk_color":           self.risk_color,
            "risk_factors":         self.risk_factors,
            "profile_code":         self.profile_code,
            "profile_zh":           self.profile_zh,
            "profile_en":           self.profile_en,
            "profile_color":        self.profile_color,
            "streak":               self.streak,
            "velocity_3d":          self.velocity_3d,
            "acceleration":         self.acceleration,
            "sponsorship_score":    self.sponsorship_score,
            "sm_state":             self.sm_state,
            "sm_state_zh":          self.sm_state_zh,
            "funnel_layer":         self.funnel_layer,
            "in_golden":            self.in_golden,
            "golden_tier":          self.golden_tier,
            "golden_conviction":    round(self.golden_conviction, 3),
            "sector":               self.sector,
            "is_tier_a":            self.is_tier_a,
            "confidence_breakdown": self.confidence_breakdown,
            "risk_breakdown":       self.risk_breakdown,
        }


@dataclass
class MarketRiskTemperature:
    date:            str
    snapshot_count:  int

    temperature:       float
    temperature_level: str     # cool/stable/warm/hot/extreme
    temperature_zh:    str
    temperature_color: str

    # Component ratios (0.0–1.0)
    elevated_risk_ratio: float   # fraction with elevated/critical risk
    distributing_ratio:  float   # distributing / (confirmed+strengthening+distributing)
    breadth_signal:      float   # 0=deteriorating, 0.5=stable, 1=improving

    # Universe counts
    total_tracked:   int
    confirmed_count: int
    strengthening_count: int
    distributing_count: int
    high_confidence_low_risk: int

    # Alerts (bilingual)
    alerts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "date":              self.date,
            "snapshot_count":    self.snapshot_count,
            "temperature":       round(self.temperature, 3),
            "temperature_level": self.temperature_level,
            "temperature_zh":    self.temperature_zh,
            "temperature_color": self.temperature_color,
            "elevated_risk_ratio":    round(self.elevated_risk_ratio, 3),
            "distributing_ratio":     round(self.distributing_ratio, 3),
            "breadth_signal":         round(self.breadth_signal, 3),
            "total_tracked":          self.total_tracked,
            "confirmed_count":        self.confirmed_count,
            "strengthening_count":    self.strengthening_count,
            "distributing_count":     self.distributing_count,
            "high_confidence_low_risk": self.high_confidence_low_risk,
            "alerts":                 self.alerts,
        }


@dataclass
class ConfidenceResult:
    date:            str
    snapshot_count:  int

    market_temperature: MarketRiskTemperature
    profiles:           dict[str, ConfidenceProfile] = field(default_factory=dict)

    # Sorted convenience views
    ideal:        list[ConfidenceProfile] = field(default_factory=list)   # high_low
    watch:        list[ConfidenceProfile] = field(default_factory=list)   # high_elevated / high_medium
    deteriorating:list[ConfidenceProfile] = field(default_factory=list)   # deteriorating
    weak:         list[ConfidenceProfile] = field(default_factory=list)   # low_any

    def as_dict(self) -> dict[str, Any]:
        return {
            "date":               self.date,
            "snapshot_count":     self.snapshot_count,
            "market_temperature": self.market_temperature.as_dict(),
            "counts": {
                "total":        len(self.profiles),
                "ideal":        len(self.ideal),
                "watch":        len(self.watch),
                "deteriorating":len(self.deteriorating),
                "weak":         len(self.weak),
            },
            "ideal":         [p.as_dict() for p in self.ideal],
            "watch":         [p.as_dict() for p in self.watch],
            "deteriorating": [p.as_dict() for p in self.deteriorating],
            "weak":          [p.as_dict() for p in self.weak],
        }


# ── Scoring functions ─────────────────────────────────────────────────────────

def _compute_confidence(
    streak:            int,
    sponsorship:       float,
    velocity_3d:       float | None,
    acceleration:      float | None,
    in_golden:         bool,
    golden_conviction: float,
    sector_top3:       bool,
    is_tier_a:         bool,
) -> tuple[float, dict[str, float], list[str]]:
    bd: dict[str, float] = {}
    factors: list[str] = []

    # Streak
    streak_contrib = min(streak / STREAK_SCALE, STREAK_CAP)
    if streak_contrib > 0:
        bd["streak"] = round(streak_contrib, 3)
        factors.append(f"連買{streak}日")

    # Sponsorship
    spon_contrib = sponsorship * SPON_WEIGHT
    if spon_contrib > 0.02:
        bd["sponsorship"] = round(spon_contrib, 3)
        factors.append(f"贊助{sponsorship:.2f}")

    # Velocity
    if velocity_3d is not None and velocity_3d > 0:
        bd["velocity_positive"] = CONF_VEL_POS
        factors.append("速度為正")

    # Acceleration
    if acceleration is not None and acceleration > 0:
        bd["acceleration_positive"] = CONF_ACCEL
        factors.append("加速中")

    # Golden layer
    if in_golden:
        bd["in_golden"] = CONF_GOLDEN
        factors.append("黃金名單")
        conviction_add = golden_conviction * CONF_CONVICTION_SCALE
        if conviction_add > 0.005:
            bd["conviction_add"] = round(conviction_add, 3)

    # Sector top-3
    if sector_top3:
        bd["sector_top3"] = CONF_SECTOR
        factors.append("族群領先")

    # Tier A
    if is_tier_a:
        bd["tier_a"] = CONF_TIER_A
        factors.append("Tier A")

    score = min(1.0, sum(bd.values()))
    return score, bd, factors


def _compute_risk(
    sm_risk_level:   str,
    sm_state:        str,
    funnel_layer:    str,
    failed_breakout: bool,
    velocity_3d:     float | None,
    acceleration:    float | None,
    streak:          int,
) -> tuple[float, str, dict[str, float], list[str]]:
    bd: dict[str, float] = {}
    factors: list[str] = []

    # State machine base risk
    base = RISK_SM_BASE.get(sm_risk_level, 0.0)
    if base > 0:
        bd["sm_base"] = base
        factors.append(f"狀態機風險:{sm_risk_level}")

    # DISTRIBUTING state adds on top
    if sm_state == S_DISTRIBUTING:
        bd["distributing"] = RISK_DISTRIBUTING
        factors.append("疑似出貨")

    # Funnel risk warning
    if funnel_layer == LAYER_RISK_WARNING:
        bd["funnel_warning"] = RISK_FUNNEL_WARN
        factors.append("漏斗風險警示")

    # Failed breakout
    if failed_breakout:
        bd["failed_breakout"] = RISK_FB
        factors.append("假突破紀錄")

    # Velocity negative
    if velocity_3d is not None and velocity_3d < 0:
        bd["velocity_negative"] = RISK_VEL_NEG
        factors.append(f"速度為負 {velocity_3d:+,.0f}")

    # Strong negative acceleration
    if acceleration is not None and acceleration < -500:
        bd["accel_negative"] = RISK_ACCEL_NEG
        factors.append(f"加速度 {acceleration:,.0f}")

    # Streak zero
    if streak == 0:
        bd["streak_zero"] = RISK_NO_STREAK
        factors.append("連買中斷")

    risk_score = min(1.0, sum(bd.values()))

    if risk_score >= 0.50:
        level = "critical"
    elif risk_score >= 0.30:
        level = "elevated"
    elif risk_score >= 0.15:
        level = "medium"
    else:
        level = "low"

    return risk_score, level, bd, factors


def _confidence_band(score: float) -> str:
    if score >= CONF_HIGH:
        return "high"
    if score >= CONF_MID:
        return "mid"
    return "low"


def _profile_code(conf_band: str, risk_level: str, deteriorating: bool) -> str:
    if deteriorating:
        return "deteriorating"
    if conf_band == "low":
        return "low_any"
    risk_band = (
        "low"      if risk_level == "low"
        else "medium"   if risk_level == "medium"
        else "elevated"    # elevated or critical both → elevated for profile
    )
    return f"{conf_band}_{risk_band}"


# ── Breadth helper ────────────────────────────────────────────────────────────

def _breadth_signal(snapshots: list[dict]) -> float:
    """
    0.0 = deteriorating  0.5 = stable  1.0 = improving
    Based on the slope of breadth_series over last 5 snapshots.
    """
    reg = regime_shift(snapshots)
    bs  = reg.get("breadth_series", [])
    if len(bs) < 3:
        return 0.5
    recent = bs[-5:]
    slope  = recent[-1] - recent[0]
    if slope > 0.02:
        return 1.0
    if slope < -0.02:
        return 0.0
    return 0.5


# ── Market temperature ────────────────────────────────────────────────────────

def _build_temperature(
    date: str,
    snapshot_count: int,
    profiles: dict[str, ConfidenceProfile],
    sm_summary,
    breadth_sig: float,
) -> MarketRiskTemperature:
    n = len(profiles)
    if n == 0:
        return MarketRiskTemperature(
            date=date, snapshot_count=snapshot_count,
            temperature=0.0, temperature_level="cool",
            temperature_zh="冷靜", temperature_color="#52B788",
            elevated_risk_ratio=0.0, distributing_ratio=0.0,
            breadth_signal=0.5, total_tracked=0,
            confirmed_count=0, strengthening_count=0,
            distributing_count=0, high_confidence_low_risk=0,
        )

    # Elevated/critical risk ratio
    elevated_n = sum(
        1 for p in profiles.values()
        if p.risk_level in ("elevated", "critical")
    )
    elev_ratio = elevated_n / n

    # Distributing ratio (among active tickers)
    conf_n    = sm_summary.state_counts.get(S_CONFIRMED, 0)
    str_n     = sm_summary.state_counts.get(S_STRENGTHENING, 0)
    dist_n    = sm_summary.state_counts.get(S_DISTRIBUTING, 0)
    denom     = conf_n + str_n + dist_n
    dist_ratio = dist_n / denom if denom > 0 else 0.0

    # Breadth component (1 = deteriorating → high risk, 0 = improving → low risk)
    breadth_risk = 1.0 - breadth_sig

    # Weighted temperature
    temperature = (
        TEMP_W_RISK_RATIO * elev_ratio
        + TEMP_W_DISTRIB  * dist_ratio
        + TEMP_W_BREADTH  * breadth_risk
    )
    temperature = min(1.0, temperature)

    # Level
    t_level = "cool"
    t_zh    = "冷靜"
    t_color = "#52B788"
    for threshold, level, zh, color in TEMP_LEVELS:
        if temperature >= threshold:
            t_level, t_zh, t_color = level, zh, color
            break

    # Alerts
    alerts: list[str] = []
    if dist_n >= 3:
        alerts.append(f"⚠ {dist_n} 支確認股進入疑似出貨 / {dist_n} confirmed tickers now distributing")
    if elev_ratio >= 0.30:
        pct = int(elev_ratio * 100)
        alerts.append(f"⚠ {pct}% 追蹤標的風險偏高或以上 / {pct}% of tickers at elevated+ risk")
    failed_n = sm_summary.state_counts.get(S_FAILED, 0)
    if failed_n >= 2:
        alerts.append(f"⚠ {failed_n} 支結構失敗 / {failed_n} tickers with failed structure")
    if breadth_sig == 0.0:
        alerts.append("⚠ 市場廣度惡化中 / Market breadth deteriorating")

    hclr = sum(1 for p in profiles.values() if p.profile_code == "high_low")

    return MarketRiskTemperature(
        date=date, snapshot_count=snapshot_count,
        temperature=temperature,
        temperature_level=t_level,
        temperature_zh=t_zh,
        temperature_color=t_color,
        elevated_risk_ratio=elev_ratio,
        distributing_ratio=dist_ratio,
        breadth_signal=breadth_sig,
        total_tracked=n,
        confirmed_count=conf_n,
        strengthening_count=str_n,
        distributing_count=dist_n,
        high_confidence_low_risk=hclr,
        alerts=alerts,
    )


# ── Sector top-3 helper ───────────────────────────────────────────────────────

def _sector_top3_set(snapshots: list[dict]) -> set[str]:
    """Return the set of sector names currently in top-3 by net_mfb."""
    if not snapshots:
        return set()
    try:
        from core.sector_intelligence import build_sector_map, _collect_per_snap
        sm  = build_sector_map(snapshots)
        per = _collect_per_snap(snapshots, sm)
        if not per:
            return set()
        latest = per[-1]["sector_data"]
        ranked = sorted(
            latest.keys(),
            key=lambda s: -sum(latest[s].get("mfb_vals", []) or [0]),
        )
        return set(ranked[:3])
    except Exception:
        return set()


# ── Deterioration detector ────────────────────────────────────────────────────

def _is_deteriorating(
    ticker:    str,
    snapshots: list[dict],
    current_conf: float,
    current_risk: float,
) -> bool:
    """
    True if confidence is falling AND risk is rising compared to 3 snapshots ago.
    Lightweight: compares streak and velocity trend without full re-run.
    """
    if len(snapshots) < 4:
        return False
    prev_snaps = snapshots[:-3]
    if not prev_snaps:
        return False
    from core.market_context import accumulation_velocity
    # Build prev records
    prev_records = [
        {**rec, "date": snap.get("date", "")}
        for snap in prev_snaps
        for rec in snap.get("stocks", [])
        if rec.get("ticker") == ticker
    ]
    if len(prev_records) < 2:
        return False
    prev_acc = accumulation_velocity(ticker, prev_records)
    prev_streak = prev_acc.get("streak", 0)
    prev_vel    = prev_acc.get("velocity_3d")

    # Current signals
    curr_records = [
        {**rec, "date": snap.get("date", "")}
        for snap in snapshots
        for rec in snap.get("stocks", [])
        if rec.get("ticker") == ticker
    ]
    from core.market_context import sponsorship_persistence
    curr_acc = accumulation_velocity(ticker, curr_records) if curr_records else {}
    curr_vel = curr_acc.get("velocity_3d")

    streak_dropped = curr_acc.get("streak", 0) < prev_streak
    vel_dropped    = (
        prev_vel is not None and curr_vel is not None
        and curr_vel < prev_vel
        and curr_vel < 0
    )
    return streak_dropped and vel_dropped


# ── Public API ────────────────────────────────────────────────────────────────

def run(snapshots: list[dict]) -> ConfidenceResult:
    """
    Run the full Confidence & Risk Profile over all snapshots.
    Returns a ConfidenceResult.
    """
    if not snapshots:
        empty_temp = MarketRiskTemperature(
            date="—", snapshot_count=0,
            temperature=0.0, temperature_level="cool",
            temperature_zh="冷靜", temperature_color="#52B788",
            elevated_risk_ratio=0.0, distributing_ratio=0.0,
            breadth_signal=0.5, total_tracked=0,
            confirmed_count=0, strengthening_count=0,
            distributing_count=0, high_confidence_low_risk=0,
        )
        return ConfidenceResult(date="—", snapshot_count=0, market_temperature=empty_temp)

    date = snapshots[-1].get("date", "?")

    # Run upstream engines
    gr         = golden_run(snapshots)
    sm_states  = sm_run_all(snapshots)
    sm_summary = sm_state_summary(snapshots)
    breadth    = _breadth_signal(snapshots)

    # Build golden lookup: ticker → GoldenEntry
    golden_map: dict[str, GoldenEntry] = {}
    for e in gr.prime + gr.strong + gr.qualified:
        golden_map[e.ticker] = e

    # Sector top-3 set
    top3_sectors = _sector_top3_set(snapshots)

    profiles: dict[str, ConfidenceProfile] = {}

    # Process all tickers visible in state machine
    for ticker, ts in sm_states.items():
        ge  = golden_map.get(ticker)
        in_golden        = ge is not None
        golden_conviction = ge.conviction if ge else 0.0
        golden_tier       = ge.tier if ge else ""
        funnel_layer      = ge.funnel_layer if ge else ts.state  # fallback

        # Confidence
        conf, conf_bd, conf_factors = _compute_confidence(
            streak=ts.streak,
            sponsorship=ts.sponsorship_score,
            velocity_3d=ts.velocity_3d,
            acceleration=ts.acceleration,
            in_golden=in_golden,
            golden_conviction=golden_conviction,
            sector_top3=ts.sector in top3_sectors,
            is_tier_a=ts.is_tier_a,
        )

        # Risk
        risk_score, risk_level, risk_bd, risk_factors = _compute_risk(
            sm_risk_level=ts.transition_risk,
            sm_state=ts.state,
            funnel_layer=funnel_layer,
            failed_breakout=ts.failed_breakout,
            velocity_3d=ts.velocity_3d,
            acceleration=ts.acceleration,
            streak=ts.streak,
        )

        # Deterioration
        det = _is_deteriorating(ticker, snapshots, conf, risk_score)

        conf_band = _confidence_band(conf)
        code      = _profile_code(conf_band, risk_level, det)

        profiles[ticker] = ConfidenceProfile(
            ticker=ticker,
            name=ts.name,
            confidence=conf,
            confidence_band=conf_band,
            confidence_zh=CONF_ZH[conf_band],
            confidence_color=CONF_COLOR[conf_band],
            confidence_factors=conf_factors,
            risk_score=risk_score,
            risk_level=risk_level,
            risk_zh=RISK_LEVEL_ZH[risk_level],
            risk_color=RISK_COLOR[risk_level],
            risk_factors=risk_factors,
            profile_code=code,
            profile_zh=PROFILE_ZH[code],
            profile_en=PROFILE_EN[code],
            profile_color=PROFILE_COLOR[code],
            streak=ts.streak,
            velocity_3d=ts.velocity_3d,
            acceleration=ts.acceleration,
            sponsorship_score=ts.sponsorship_score,
            sm_state=ts.state,
            sm_state_zh=ts.state_zh,
            funnel_layer=funnel_layer,
            in_golden=in_golden,
            golden_tier=golden_tier,
            golden_conviction=golden_conviction,
            sector=ts.sector,
            is_tier_a=ts.is_tier_a,
            confidence_breakdown=conf_bd,
            risk_breakdown=risk_bd,
        )

    # Build temperature
    temperature = _build_temperature(date, len(snapshots), profiles, sm_summary, breadth)

    # Sort into views
    def _by_conf(lst: list[ConfidenceProfile]) -> list[ConfidenceProfile]:
        return sorted(lst, key=lambda p: (-p.confidence, p.risk_score))

    ideal         = _by_conf([p for p in profiles.values() if p.profile_code == "high_low"])
    watch         = _by_conf([p for p in profiles.values()
                               if p.profile_code in ("high_elevated", "high_medium")])
    deteriorating = _by_conf([p for p in profiles.values() if p.profile_code == "deteriorating"])
    weak          = _by_conf([p for p in profiles.values() if p.profile_code == "low_any"])

    return ConfidenceResult(
        date=date,
        snapshot_count=len(snapshots),
        market_temperature=temperature,
        profiles=profiles,
        ideal=ideal,
        watch=watch,
        deteriorating=deteriorating,
        weak=weak,
    )


def ticker_profile(ticker: str, snapshots: list[dict]) -> ConfidenceProfile | None:
    """Return the ConfidenceProfile for a single ticker, or None if not found."""
    result = run(snapshots)
    return result.profiles.get(ticker)


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

    p = argparse.ArgumentParser(description="SCD Confidence & Risk Profile")
    p.add_argument("--json",   action="store_true")
    p.add_argument("--ticker", default=None, help="Single ticker deep-dive")
    p.add_argument("--all",    action="store_true", help="Show all profile groups")
    args = p.parse_args()

    cr = run(snaps)
    mt = cr.market_temperature

    if args.json:
        print(_json.dumps(cr.as_dict(), ensure_ascii=False, indent=2, default=str))
        import sys; sys.exit(0)

    W = 70
    print(f"\n{'═'*W}")
    print(f"  信心度 & 風險側寫  CONFIDENCE & RISK PROFILE")
    print(f"  {cr.date}  ({cr.snapshot_count} snapshots)  |  追蹤 {mt.total_tracked} 支")
    print(f"{'═'*W}")

    # Temperature banner
    bar_len = int(mt.temperature * 30)
    bar     = "█" * bar_len + "░" * (30 - bar_len)
    print(f"\n  市場風險溫度 Market Risk Temperature")
    print(f"  [{bar}]  {mt.temperature:.0%}  {mt.temperature_zh} / {mt.temperature_level.upper()}")
    print(f"  ├ 高風險比例:    {mt.elevated_risk_ratio:.0%}")
    print(f"  ├ 出貨比例:      {mt.distributing_ratio:.0%}")
    print(f"  ├ 廣度訊號:      {'↑改善' if mt.breadth_signal >= 0.7 else ('→穩定' if mt.breadth_signal >= 0.3 else '↓惡化')}")
    print(f"  └ 強勢低風險數:  {mt.high_confidence_low_risk} 支")

    if mt.alerts:
        print()
        for a in mt.alerts:
            print(f"  {a}")

    if args.ticker:
        t = args.ticker.strip()
        prof = cr.profiles.get(t)
        if not prof:
            print(f"\n  {t} not found in profiles.")
            import sys; sys.exit(0)
        print(f"\n{'─'*W}")
        print(f"  {prof.ticker} {prof.name}")
        print(f"  信心: {prof.confidence:.2f} [{prof.confidence_zh}]  "
              f"風險: {prof.risk_score:.2f} [{prof.risk_zh}]")
        print(f"  側寫: {prof.profile_zh} / {prof.profile_en}")
        print(f"  State: {prof.sm_state_zh}  Funnel: {prof.funnel_layer}  "
              f"Golden: {'✓ '+prof.golden_tier if prof.in_golden else '—'}")
        print(f"  連買{prof.streak}日  贊助{prof.sponsorship_score:.2f}  "
              f"速度{prof.velocity_3d:+,.0f}" if prof.velocity_3d is not None
              else f"  連買{prof.streak}日  贊助{prof.sponsorship_score:.2f}")
        print(f"\n  信心來源: {', '.join(prof.confidence_factors) or '—'}")
        print(f"  風險來源: {', '.join(prof.risk_factors) or '—'}")
        print(f"\n  信心分解:")
        for k, v in prof.confidence_breakdown.items():
            print(f"    {k:<28} +{v:.3f}")
        print(f"  風險分解:")
        for k, v in prof.risk_breakdown.items():
            print(f"    {k:<28} +{v:.3f}")
        import sys; sys.exit(0)

    def _print_group(
        entries: list[ConfidenceProfile],
        title: str,
        max_n: int = 10,
    ) -> None:
        if not entries:
            return
        print(f"\n── {title} ({len(entries)}) {'─'*(W - len(title) - 7)}")
        for prof in entries[:max_n]:
            tier_a  = "[A]" if prof.is_tier_a else "   "
            gold_tag = f"★{prof.golden_conviction:.2f}" if prof.in_golden else "     "
            vel_str  = (f"v{prof.velocity_3d:+,.0f}" if prof.velocity_3d is not None else "v——")
            print(
                f"  {tier_a} {prof.ticker} {prof.name:<10}  "
                f"C:{prof.confidence:.2f} R:{prof.risk_score:.2f}  "
                f"{gold_tag}  {prof.sm_state_zh:<6}  "
                f"連買{prof.streak}日  贊助{prof.sponsorship_score:.2f}  {vel_str}"
            )
        if len(entries) > max_n:
            print(f"  … 另 {len(entries) - max_n} 支")

    _print_group(cr.ideal,         "強勢低風險 High Confidence / Low Risk")
    _print_group(cr.watch,         "強勢但有警示 Strong with Warning")
    _print_group(cr.deteriorating, "結構惡化中 Deteriorating")

    if args.all:
        _print_group(cr.weak, "信號不足 Insufficient Signal")

    print()
