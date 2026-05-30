"""SCD Engine — Market Context Engine  (P3d)
市場狀態統一引擎

Single source of truth for "what the market is doing today".

Aggregates all temporal modules into one unified MarketState object:

    ┌─────────────────────────────────────────────────────────┐
    │  Inputs                                                 │
    │  ──────                                                 │
    │  core.market_context     regime_shift, accumulation_    │
    │                          velocity, sponsorship_         │
    │                          persistence, failed_breakout_  │
    │                          memory, full_ticker_context    │
    │                                                         │
    │  core.sector_intelligence  sector_summary,              │
    │                            sector_strength,             │
    │                            sector_time_series           │
    │                                                         │
    │  tools.temporal.streak_analyzer     analyze()           │
    │  tools.temporal.persistence_ranker  rank()              │
    │  tools.temporal.transition_detector detect()            │
    │  tools.temporal.regime_monitor      observe_window()    │
    │                                                         │
    │  core.narrative_engine   generate()                     │
    └─────────────────────────────────────────────────────────┘
                          │
                          ▼
              core.market_state.build()
                          │
                          ▼
              MarketState  (pure dataclass dict)

Design rules
────────────
- Strictly observational: no predictions, no recommendations
- All inputs are pre-loaded snapshot dicts (same shape everywhere)
- Deterministic: same inputs → same output, always
- No I/O inside build()  — callers load snapshots, pass them in
- All public names are stable for cockpit / UI consumers

Public API
──────────
    build(snapshots)                → MarketState dict
    market_condition(snapshots)     → just the condition layer (fast)
    capital_flow_summary(snapshots) → just the flow layer
    leadership_map(snapshots)       → just the leadership layer
"""
from __future__ import annotations

import statistics
import sys
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Any

_HERE     = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

# ── Core modules ─────────────────────────────────────────────────────────────
from core.market_context import (
    regime_shift,
    accumulation_velocity,
    sponsorship_persistence,
    failed_breakout_memory,
    full_ticker_context,
    leadership_rotation,
)
from core.sector_intelligence import (
    build_sector_map,
    sector_summary,
    sector_strength,
    sector_time_series,
    sector_meta,
)
from core.watchlists import TIER_A, SECTOR_GROUPS, build_name_map
from core.narrative_engine import generate as _narrative_generate

# ── Temporal tools ────────────────────────────────────────────────────────────
try:
    from tools.temporal.streak_analyzer     import analyze     as _streak_analyze
    from tools.temporal.persistence_ranker  import rank        as _persistence_rank
    from tools.temporal.transition_detector import detect      as _transition_detect
    _TEMPORAL_AVAILABLE = True
except ImportError:
    _TEMPORAL_AVAILABLE = False


# =============================================================================
# Condition constants
# =============================================================================

class MarketCondition:
    RISK_ON       = "risk_on"
    MILD_RISK_ON  = "mild_risk_on"
    NEUTRAL       = "neutral"
    MILD_RISK_OFF = "mild_risk_off"
    RISK_OFF      = "risk_off"
    TRANSITIONING = "transitioning"

    LABELS_ZH = {
        "risk_on":       "強勢進攻",
        "mild_risk_on":  "溫和偏多",
        "neutral":       "中性整理",
        "mild_risk_off": "偏弱整理",
        "risk_off":      "全面撤退",
        "transitioning": "體制轉換中",
    }
    LABELS_EN = {
        "risk_on":       "Risk-On / Offensive",
        "mild_risk_on":  "Mild Risk-On",
        "neutral":       "Neutral / Consolidating",
        "mild_risk_off": "Mild Risk-Off",
        "risk_off":      "Risk-Off / Retreat",
        "transitioning": "Transitioning",
    }
    COLORS = {
        "risk_on":       "#52B788",
        "mild_risk_on":  "#7EB8D4",
        "neutral":       "#6B8EAA",
        "mild_risk_off": "#C47A5A",
        "risk_off":      "#E05C7A",
        "transitioning": "#D4A84B",
    }

    @classmethod
    def label_zh(cls, c: str) -> str: return cls.LABELS_ZH.get(c, c)
    @classmethod
    def label_en(cls, c: str) -> str: return cls.LABELS_EN.get(c, c)
    @classmethod
    def color(cls, c: str) -> str:    return cls.COLORS.get(c, "#6B8EAA")


class BreadthCondition:
    BROAD       = "broad"        # ≥ 70%
    HEALTHY     = "healthy"      # 50–70%
    MIXED       = "mixed"        # 30–50%
    NARROW      = "narrow"       # 15–30%
    VERY_NARROW = "very_narrow"  # < 15%

    LABELS_ZH = {
        "broad":       "全面性上漲",
        "healthy":     "健康廣度",
        "mixed":       "廣度中性",
        "narrow":      "廣度偏窄",
        "very_narrow": "極度集中",
    }
    LABELS_EN = {
        "broad":       "Broad Advance",
        "healthy":     "Healthy Breadth",
        "mixed":       "Mixed Breadth",
        "narrow":      "Narrow Leadership",
        "very_narrow": "Highly Concentrated",
    }

    @classmethod
    def from_pct(cls, pct: float) -> str:
        if pct >= 0.70: return cls.BROAD
        if pct >= 0.50: return cls.HEALTHY
        if pct >= 0.30: return cls.MIXED
        if pct >= 0.15: return cls.NARROW
        return cls.VERY_NARROW

    @classmethod
    def label_zh(cls, c: str) -> str: return cls.LABELS_ZH.get(c, c)
    @classmethod
    def label_en(cls, c: str) -> str: return cls.LABELS_EN.get(c, c)


class VolumeCondition:
    SURGING  = "surging"   # vol_index ≥ 1.5
    ELEVATED = "elevated"  # 1.15–1.5
    NORMAL   = "normal"    # 0.85–1.15
    LIGHT    = "light"     # 0.6–0.85
    VERY_LOW = "very_low"  # < 0.6

    LABELS_ZH = {
        "surging":  "量能爆發",
        "elevated": "量能偏高",
        "normal":   "量能正常",
        "light":    "量能偏低",
        "very_low": "極度縮量",
    }
    LABELS_EN = {
        "surging":  "Surging Volume",
        "elevated": "Elevated Volume",
        "normal":   "Normal Volume",
        "light":    "Light Volume",
        "very_low": "Very Low Volume",
    }

    @classmethod
    def from_index(cls, idx: float) -> str:
        if idx >= 1.50: return cls.SURGING
        if idx >= 1.15: return cls.ELEVATED
        if idx >= 0.85: return cls.NORMAL
        if idx >= 0.60: return cls.LIGHT
        return cls.VERY_LOW

    @classmethod
    def label_zh(cls, c: str) -> str: return cls.LABELS_ZH.get(c, c)
    @classmethod
    def label_en(cls, c: str) -> str: return cls.LABELS_EN.get(c, c)


class LiquidityCondition:
    HIGH    = "high"     # top5_branch_coverage ≥ 0.7
    MEDIUM  = "medium"   # 0.4–0.7
    LOW     = "low"      # 0.2–0.4
    SPARSE  = "sparse"   # < 0.2

    LABELS_ZH = {
        "high":   "分點覆蓋充足",
        "medium": "分點覆蓋中等",
        "low":    "分點覆蓋偏低",
        "sparse": "分點覆蓋稀疏",
    }
    LABELS_EN = {
        "high":   "High Branch Coverage",
        "medium": "Medium Branch Coverage",
        "low":    "Low Branch Coverage",
        "sparse": "Sparse Branch Coverage",
    }

    @classmethod
    def from_coverage(cls, cov: float) -> str:
        if cov >= 0.70: return cls.HIGH
        if cov >= 0.40: return cls.MEDIUM
        if cov >= 0.20: return cls.LOW
        return cls.SPARSE

    @classmethod
    def label_zh(cls, c: str) -> str: return cls.LABELS_ZH.get(c, c)
    @classmethod
    def label_en(cls, c: str) -> str: return cls.LABELS_EN.get(c, c)


# =============================================================================
# Layer builders  (private — each returns a clean dict)
# =============================================================================

def _build_condition_layer(snapshots: list[dict]) -> dict[str, Any]:
    """
    Layer 1: Market State Summary
    ─────────────────────────────
    condition, breadth, volume, liquidity — all from regime_shift() +
    per-snapshot observations.
    """
    if not snapshots:
        return _empty_condition()

    reg = regime_shift(snapshots)

    # Map regime color / label → MarketCondition key
    label_to_cond = {
        "強勢進攻": MarketCondition.RISK_ON,
        "溫和偏多": MarketCondition.MILD_RISK_ON,
        "中性整理": MarketCondition.NEUTRAL,
        "偏弱整理": MarketCondition.MILD_RISK_OFF,
        "全面撤退": MarketCondition.RISK_OFF,
    }
    base_cond = label_to_cond.get(reg["regime_label_zh"], MarketCondition.NEUTRAL)

    # If a transition was just detected → override to TRANSITIONING
    condition = MarketCondition.TRANSITIONING if reg["transition_detected"] else base_cond

    breadth_pct = reg["latest_breadth"]
    vol_idx     = reg.get("latest_vol_index", 1.0)

    breadth_cond   = BreadthCondition.from_pct(breadth_pct)
    volume_cond    = VolumeCondition.from_index(vol_idx)

    # Liquidity proxy: top5_branch_coverage from latest snapshot
    latest = snapshots[-1]
    stocks = latest.get("stocks", [])
    if stocks:
        cov_vals = [
            1 if s.get("top5_branches") else 0
            for s in stocks
        ]
        liquidity_cov = sum(cov_vals) / len(cov_vals)
    else:
        liquidity_cov = 0.0
    liquidity_cond = LiquidityCondition.from_coverage(liquidity_cov)

    # Breadth delta (today vs yesterday)
    breadth_series = reg.get("breadth_series", [])
    breadth_delta  = None
    if len(breadth_series) >= 2:
        breadth_delta = round((breadth_series[-1] - breadth_series[-2]) * 100, 2)

    return {
        "date":              latest.get("date", "?"),
        "condition":         condition,
        "condition_zh":      MarketCondition.label_zh(condition),
        "condition_en":      MarketCondition.label_en(condition),
        "condition_color":   MarketCondition.color(condition),
        "breadth":           round(breadth_pct * 100, 2),
        "breadth_condition": breadth_cond,
        "breadth_zh":        BreadthCondition.label_zh(breadth_cond),
        "breadth_en":        BreadthCondition.label_en(breadth_cond),
        "breadth_delta":     breadth_delta,
        "breadth_trend":     reg.get("breadth_trend", "flat"),
        "avg_change_pct":    round(reg.get("latest_avg_chg", 0.0), 3),
        "volume_condition":  volume_cond,
        "volume_zh":         VolumeCondition.label_zh(volume_cond),
        "volume_en":         VolumeCondition.label_en(volume_cond),
        "volume_index":      round(vol_idx, 3),
        "liquidity_condition": liquidity_cond,
        "liquidity_zh":      LiquidityCondition.label_zh(liquidity_cond),
        "liquidity_en":      LiquidityCondition.label_en(liquidity_cond),
        "liquidity_coverage": round(liquidity_cov, 3),
        "transition_detected": reg["transition_detected"],
        "transition_note":   reg.get("transition_note", ""),
        "regime_color":      reg["regime_color"],
        # Full series for charts
        "dates":             reg["dates"],
        "breadth_series":    reg.get("breadth_series", []),
        "avg_chg_series":    reg.get("avg_chg_series", []),
        "vol_series":        reg.get("vol_series", []),
    }


def _build_flow_layer(snapshots: list[dict]) -> dict[str, Any]:
    """
    Layer 2: Capital Flow Summary
    ─────────────────────────────
    Where money is going and leaving, aggregated by sector.
    """
    if not snapshots:
        return _empty_flow()

    sm      = build_sector_map(snapshots)
    summary = sector_summary(snapshots, sm)
    ts      = sector_time_series(snapshots, sm)

    # Inflow sectors (positive net_mfb + positive acceleration)
    accel   = summary.get("accel_map", {})
    net_mfb = summary.get("latest_net_mfb", {})

    inflow_sectors  = sorted(
        [s for s, v in net_mfb.items() if v > 0],
        key=lambda s: -net_mfb[s],
    )
    outflow_sectors = sorted(
        [s for s, v in net_mfb.items() if v < 0],
        key=lambda s: net_mfb[s],
    )
    accelerating_sectors = sorted(
        [s for s, a in accel.items() if a > 0 and net_mfb.get(s, 0) > 0],
        key=lambda s: -accel[s],
    )
    decelerating_sectors = sorted(
        [s for s, a in accel.items() if a < 0 and net_mfb.get(s, 0) > 0],
        key=lambda s: accel[s],
    )

    # Enrich with metadata
    def _enrich(sectors: list[str]) -> list[dict]:
        return [
            {
                "sector":    s,
                "zh":        sector_meta(s).get("zh", s),
                "en":        sector_meta(s).get("en", s),
                "color":     sector_meta(s).get("color", "#6B8EAA"),
                "icon":      sector_meta(s).get("icon", "○"),
                "net_mfb":   net_mfb.get(s, 0),
                "accel":     accel.get(s),
                "breadth":   summary["sector_strength"].get(s, {}).get("breadth", 0),
                "avg_chg":   summary["sector_strength"].get(s, {}).get("avg_chg", 0),
                "momentum":  summary["momentum_map"].get(s, 0),
            }
            for s in sectors
        ]

    return {
        "leading_sector":          summary.get("leading_sector"),
        "leading_zh":              summary.get("leading_zh", "—"),
        "leading_en":              summary.get("leading_en", "—"),
        "weakening_sector":        summary.get("weakening_sector"),
        "weakening_zh":            summary.get("weakening_zh", "—"),
        "weakening_en":            summary.get("weakening_en", "—"),
        "emerging_sector":         summary.get("emerging_sector"),
        "emerging_zh":             summary.get("emerging_zh", "—"),
        "emerging_en":             summary.get("emerging_en", "—"),
        "inflow_sectors":          _enrich(inflow_sectors),
        "outflow_sectors":         _enrich(outflow_sectors),
        "accelerating_sectors":    _enrich(accelerating_sectors),
        "decelerating_sectors":    _enrich(decelerating_sectors),
        "sector_rank":             summary.get("sector_rank", []),
        "sector_strength":         summary.get("sector_strength", {}),
        "rotation_detected":       summary.get("rotation_detected", False),
        "named_rotations":         summary.get("named_rotations", []),
        "rotation_events":         summary.get("rotation_events", []),
        "momentum_map":            summary.get("momentum_map", {}),
        "sector_time_series":      ts,
    }


def _build_leadership_layer(snapshots: list[dict]) -> dict[str, Any]:
    """
    Layer 3: Leadership Map
    ────────────────────────
    Top persistent stocks, strongest accumulation clusters,
    weakest breakdown clusters.
    Uses streak_analyzer + persistence_ranker + transition_detector
    where available; falls back to market_context.full_ticker_context.
    """
    if not snapshots:
        return _empty_leadership()

    name_map = build_name_map(snapshots)

    # ── All tickers seen ─────────────────────────────────────────────────
    all_tickers: set[str] = set()
    for snap in snapshots:
        for s in snap.get("stocks", []):
            t = s.get("ticker", "")
            if t:
                all_tickers.add(t)

    latest_stocks = {s["ticker"]: s for s in snapshots[-1].get("stocks", [])}

    # ── Per-ticker full context ──────────────────────────────────────────
    ticker_ctx: dict[str, dict] = {}
    for t in all_tickers:
        ticker_ctx[t] = full_ticker_context(t, snapshots)

    # ── Streak / persistence data ────────────────────────────────────────
    streak_rows:      list[Any] = []
    persistence_rows: list[Any] = []
    recent_transitions: list[Any] = []

    if _TEMPORAL_AVAILABLE:
        try:
            streak_rows      = _streak_analyze(min_appearances=2)
        except Exception:
            pass
        try:
            persistence_rows = _persistence_rank(mode="composite")
        except Exception:
            pass
        try:
            recent_transitions = _transition_detect(kinds=("CHANGE_PCT_SIGN",))
        except Exception:
            pass

    # ── Top persistent leaders ───────────────────────────────────────────
    # Sort by: current_streak desc, then coverage desc
    def _streak_key(t: str) -> tuple:
        ctx = ticker_ctx[t]
        acc = ctx["accumulation"]
        sp  = ctx["sponsorship"]
        return (
            -(acc.get("streak", 0)),
            -(acc.get("net_cumulative") or 0),
            -(sp.get("persistence_score") or 0),
        )

    top_persistent = sorted(
        [t for t in all_tickers if ticker_ctx[t]["accumulation"]["streak"] >= 2],
        key=_streak_key,
    )[:15]

    # ── Strongest accumulation clusters (streak ≥ 3 + high sponsorship) ──
    strong_accum = [
        t for t in all_tickers
        if (ticker_ctx[t]["accumulation"]["streak"] >= 3
            and (ticker_ctx[t]["sponsorship"]["persistence_score"] or 0) >= 0.4)
    ]
    strong_accum.sort(key=_streak_key)

    # ── Weakest / breakdown clusters (failed breakout OR negative streak) ─
    breakdown = [
        t for t in all_tickers
        if ticker_ctx[t]["failed_breakout"]["failed_breakout_detected"]
    ]
    breakdown.sort(key=lambda t: -(ticker_ctx[t]["failed_breakout"]["retreat_days"] or 0))

    # ── Enrich a ticker into a display record ────────────────────────────
    def _enrich_ticker(t: str) -> dict[str, Any]:
        ctx   = ticker_ctx[t]
        acc   = ctx["accumulation"]
        sp    = ctx["sponsorship"]
        fb    = ctx["failed_breakout"]
        stock = latest_stocks.get(t, {})
        return {
            "ticker":           t,
            "name":             name_map.get(t, t),
            "price":            stock.get("current_price"),
            "change_pct":       stock.get("change_pct"),
            "main_force_buy":   stock.get("main_force_buy"),
            "streak":           acc.get("streak", 0),
            "net_cumulative":   acc.get("net_cumulative") or 0,
            "velocity_3d":      acc.get("velocity_3d"),
            "acceleration":     acc.get("acceleration"),
            "accum_label_zh":   acc.get("label_zh", ""),
            "accum_label_en":   acc.get("label_en", ""),
            "sponsorship_score": sp.get("persistence_score", 0),
            "top_broker":       sp.get("top_persistent_broker"),
            "top_broker_days":  sp.get("top_broker_days", 0),
            "failed_breakout":  fb.get("failed_breakout_detected", False),
            "fb_label_zh":      fb.get("label_zh", ""),
            "is_tier_a":        t in TIER_A,
            "tier_a_name":      TIER_A.get(t, {}).get("name", ""),
        }

    # ── Streak distribution for breadth-of-leadership gauge ──────────────
    streak_dist: dict[str, int] = {"0": 0, "1": 0, "2": 0, "3+": 0}
    for t in all_tickers:
        s = ticker_ctx[t]["accumulation"]["streak"]
        if   s == 0: streak_dist["0"] += 1
        elif s == 1: streak_dist["1"] += 1
        elif s == 2: streak_dist["2"] += 1
        else:        streak_dist["3+"] += 1

    # ── Recent sign transitions ──────────────────────────────────────────
    sign_transitions: list[dict] = []
    for tr in (recent_transitions or [])[-30:]:
        if hasattr(tr, "__dict__"):
            sign_transitions.append(tr.__dict__)
        elif hasattr(tr, "_asdict"):
            sign_transitions.append(tr._asdict())
        else:
            try:
                import dataclasses
                sign_transitions.append(dataclasses.asdict(tr))
            except Exception:
                sign_transitions.append(str(tr))  # type: ignore[assignment]

    return {
        "top_persistent":      [_enrich_ticker(t) for t in top_persistent],
        "strong_accumulation": [_enrich_ticker(t) for t in strong_accum],
        "breakdown_cluster":   [_enrich_ticker(t) for t in breakdown],
        "streak_distribution": streak_dist,
        "total_universe":      len(all_tickers),
        "with_streak_2plus":   len(top_persistent),
        "with_failed_breakout": len(breakdown),
        "sign_transitions":    sign_transitions,
    }


def _build_narrative_layer(
    snapshots:  list[dict],
    condition:  dict[str, Any],
    flow:       dict[str, Any],
    leadership: dict[str, Any],
) -> dict[str, Any]:
    """
    Layer 4: Market Narrative
    ─────────────────────────
    Calls narrative_engine.generate() and enriches with module context.
    Falls back to a deterministic rule-based summary if engine unavailable.
    """
    if not snapshots:
        return {"summary_zh": "尚無資料", "summary_en": "No data available.",
                "bullets_zh": [], "bullets_en": [], "source": "none"}

    # Try narrative engine first
    try:
        narr = _narrative_generate(snapshots)
        if narr:
            return {**narr, "source": "narrative_engine"}
    except Exception:
        pass

    # Fallback: rule-based deterministic narrative
    cond_zh  = condition.get("condition_zh", "未知")
    cond_en  = condition.get("condition_en", "Unknown")
    breadth  = condition.get("breadth", 0)
    b_zh     = condition.get("breadth_zh", "")
    vol_zh   = condition.get("volume_zh", "")
    lead_zh  = flow.get("leading_zh", "—")
    weak_zh  = flow.get("weakening_zh", "—")
    emrg_zh  = flow.get("emerging_zh", "—")
    rot      = flow.get("rotation_detected", False)
    n_top    = len(leadership.get("top_persistent", []))
    n_break  = len(leadership.get("breakdown_cluster", []))
    date     = condition.get("date", "?")

    bullets_zh = [
        f"市場體制：{cond_zh}，廣度 {breadth:.1f}%（{b_zh}）",
        f"量能狀態：{vol_zh}",
        f"板塊主力：{lead_zh}",
    ]
    if rot:
        named = [nr["pattern_zh"] for nr in flow.get("named_rotations", [])]
        bullets_zh.append(f"偵測到輪動：{', '.join(named) if named else '板塊排名變動'}")
    if weak_zh and weak_zh != "—":
        bullets_zh.append(f"動能轉弱：{weak_zh}")
    if emrg_zh and emrg_zh != "—":
        bullets_zh.append(f"新興動能：{emrg_zh}")
    if n_top:
        bullets_zh.append(f"持續吸籌標的：{n_top} 支（連買 2 日以上）")
    if n_break:
        bullets_zh.append(f"假突破警報：{n_break} 支")

    bullets_en = [
        f"Market condition: {cond_en}, breadth {breadth:.1f}%",
        f"Volume: {condition.get('volume_en', '')}",
        f"Leading sector: {flow.get('leading_en', '—')}",
    ]
    if rot:
        named_en = [nr["pattern_en"] for nr in flow.get("named_rotations", [])]
        bullets_en.append(f"Rotation detected: {', '.join(named_en) if named_en else 'Sector rank shift'}")
    if n_top:
        bullets_en.append(f"Persistent accumulators: {n_top} tickers (2+ day streak)")
    if n_break:
        bullets_en.append(f"Failed breakout alerts: {n_break} tickers")

    summary_zh = f"{date}市場：{cond_zh}，廣度{breadth:.1f}%，板塊主力{lead_zh}。" + (
        f"偵測到板塊輪動。" if rot else ""
    )
    summary_en = f"{date}: {cond_en}. Breadth {breadth:.1f}%. Leading sector {flow.get('leading_en','—')}." + (
        " Rotation detected." if rot else ""
    )

    return {
        "summary_zh": summary_zh,
        "summary_en": summary_en,
        "bullets_zh": bullets_zh,
        "bullets_en": bullets_en,
        "source":     "rule_based_fallback",
    }


# =============================================================================
# Public API
# =============================================================================

def market_condition(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Fast path — just the condition layer (regime + breadth + volume + liquidity).
    Use when you only need the top-level market state without full sector/ticker detail.
    """
    return _build_condition_layer(snapshots)


def capital_flow_summary(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Sector-level capital flow layer only.
    Where money is going / leaving, rotation events, sector timeseries.
    """
    return _build_flow_layer(snapshots)


def leadership_map(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Ticker-level leadership layer only.
    Top persistent stocks, accumulation clusters, breakdown clusters.
    """
    return _build_leadership_layer(snapshots)


def build(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build the complete MarketState — all four layers unified.

    Returns
    ───────
    {
        "date":         str,
        "condition":    { condition, breadth, volume, liquidity, ... },
        "flow":         { leading/weakening/emerging sector, inflow/outflow, rotation, ... },
        "leadership":   { top_persistent, strong_accumulation, breakdown_cluster, ... },
        "narrative":    { summary_zh, summary_en, bullets_zh, bullets_en, source },
        "meta": {
            "snapshot_count":   int,
            "temporal_available": bool,
        }
    }
    """
    if not snapshots:
        return _empty_state()

    condition  = _build_condition_layer(snapshots)
    flow       = _build_flow_layer(snapshots)
    leadership = _build_leadership_layer(snapshots)
    narrative  = _build_narrative_layer(snapshots, condition, flow, leadership)

    return {
        "date":      condition["date"],
        "condition": condition,
        "flow":      flow,
        "leadership": leadership,
        "narrative": narrative,
        "meta": {
            "snapshot_count":     len(snapshots),
            "temporal_available": _TEMPORAL_AVAILABLE,
        },
    }


# =============================================================================
# Empty sentinels
# =============================================================================

def _empty_condition() -> dict[str, Any]:
    return dict(
        date="—", condition=MarketCondition.NEUTRAL,
        condition_zh="中性整理", condition_en="Neutral", condition_color="#6B8EAA",
        breadth=0.0, breadth_condition=BreadthCondition.MIXED,
        breadth_zh="廣度中性", breadth_en="Mixed Breadth",
        breadth_delta=None, breadth_trend="flat", avg_change_pct=0.0,
        volume_condition=VolumeCondition.NORMAL, volume_zh="量能正常", volume_en="Normal Volume",
        volume_index=1.0, liquidity_condition=LiquidityCondition.LOW,
        liquidity_zh="分點覆蓋偏低", liquidity_en="Low Branch Coverage", liquidity_coverage=0.0,
        transition_detected=False, transition_note="", regime_color="#6B8EAA",
        dates=[], breadth_series=[], avg_chg_series=[], vol_series=[],
    )


def _empty_flow() -> dict[str, Any]:
    return dict(
        leading_sector=None, leading_zh="—", leading_en="—",
        weakening_sector=None, weakening_zh="—", weakening_en="—",
        emerging_sector=None, emerging_zh="—", emerging_en="—",
        inflow_sectors=[], outflow_sectors=[],
        accelerating_sectors=[], decelerating_sectors=[],
        sector_rank=[], sector_strength={},
        rotation_detected=False, named_rotations=[], rotation_events=[],
        momentum_map={}, sector_time_series={"dates": [], "series": {}},
    )


def _empty_leadership() -> dict[str, Any]:
    return dict(
        top_persistent=[], strong_accumulation=[], breakdown_cluster=[],
        streak_distribution={"0": 0, "1": 0, "2": 0, "3+": 0},
        total_universe=0, with_streak_2plus=0, with_failed_breakout=0,
        sign_transitions=[],
    )


def _empty_state() -> dict[str, Any]:
    return dict(
        date="—",
        condition=_empty_condition(),
        flow=_empty_flow(),
        leadership=_empty_leadership(),
        narrative={"summary_zh": "尚無資料", "summary_en": "No data.",
                   "bullets_zh": [], "bullets_en": [], "source": "none"},
        meta={"snapshot_count": 0, "temporal_available": _TEMPORAL_AVAILABLE},
    )


# =============================================================================
# CLI runner
# =============================================================================

def _cli_print(state: dict) -> None:
    """Pretty-print a full market state dict to stdout."""
    cond = state.get("condition") or {}
    flow = state.get("flow") or {}
    lead = state.get("leadership") or {}
    narr = state.get("narrative") or {}

    print(f"\n{'═'*64}")
    print(f"  市場狀態引擎  MARKET STATE ENGINE  {cond.get('date', state.get('date','?'))}")
    print(f"{'═'*64}")

    print(f"\n── 市場條件 Market Condition ───────────────────────────────")
    print(f"  體制    {cond.get('condition_zh','?'):<14} / {cond.get('condition_en','?')}")
    print(f"  廣度    {cond.get('breadth',0):.1f}%  ({cond.get('breadth_zh','')})"
          + (f"  Δ{cond['breadth_delta']:+.1f}%" if cond.get('breadth_delta') is not None else ""))
    print(f"  量能    {cond.get('volume_zh','')} (指數 {cond.get('volume_index',1):.2f}×)")
    print(f"  流動性  {cond.get('liquidity_zh','')} (覆蓋率 {cond.get('liquidity_coverage',0)*100:.0f}%)")
    if cond.get("transition_detected"):
        print(f"  ⚡ {cond.get('transition_note','')}")

    print(f"\n── 資金流向 Capital Flow ───────────────────────────────────")
    print(f"  主導板塊  {flow.get('leading_zh','—'):<14} / {flow.get('leading_en','—')}")
    print(f"  轉弱板塊  {flow.get('weakening_zh','—'):<14} / {flow.get('weakening_en','—')}")
    print(f"  新興板塊  {flow.get('emerging_zh','—'):<14} / {flow.get('emerging_en','—')}")

    if flow.get("rotation_detected"):
        print(f"  ⟳ 輪動偵測:")
        for nr in flow.get("named_rotations", [])[:3]:
            print(f"     • {nr.get('pattern_zh','')}  /  {nr.get('pattern_en','')}")

    inflow = flow.get("inflow_sectors") or []
    if inflow:
        print(f"\n  資金流入板塊 Inflow Sectors:")
        for sec in inflow[:6]:
            bar = "█" * min(int(abs(sec.get("net_mfb", 0)) / 300), 24)
            mom = "↑" if sec.get("momentum", 0) > 0 else ("↓" if sec.get("momentum", 0) < 0 else "→")
            print(f"    {sec.get('icon','○')} {sec.get('zh',''):10s}  {sec.get('net_mfb',0):+8,}張  "
                  f"廣度{sec.get('breadth',0)*100:.0f}%  {mom}  {bar}")

    outflow = flow.get("outflow_sectors") or []
    if outflow:
        print(f"\n  資金流出板塊 Outflow Sectors:")
        for sec in outflow[:3]:
            print(f"    {sec.get('icon','○')} {sec.get('zh',''):10s}  {sec.get('net_mfb',0):+8,}張")

    print(f"\n── 領導圖譜 Leadership Map ─────────────────────────────────")
    top = lead.get("top_persistent") or []
    print(f"  持續吸籌 Top Persistent ({len(top)} 支):")
    for t in top[:10]:
        price  = f"NT${t['price']:,.0f}" if t.get("price") else "—"
        chg    = f"{t['change_pct']:+.1f}%" if t.get("change_pct") is not None else ""
        tier   = " [A]" if t.get("is_tier_a") else ""
        print(f"    {t['ticker']}{tier} {t.get('name',''):<8}  {price} {chg:<7}  "
              f"連買{t['streak']}日  累計{t.get('net_cumulative',0):+,}張  "
              f"贊助{t.get('sponsorship_score',0):.2f}")

    dist   = lead.get("streak_distribution", {})
    total  = lead.get("total_universe", 0)
    print(f"\n  連買天數分布 Streak Distribution (宇宙 {total} 支):")
    print(f"    0日={dist.get('0',0)}  1日={dist.get('1',0)}  "
          f"2日={dist.get('2',0)}  3+日={dist.get('3+',0)}")

    strong = lead.get("strong_accumulation") or []
    if strong:
        print(f"\n  強力吸籌叢集 Strong Accumulation Cluster ({len(strong)} 支):")
        for t in strong[:5]:
            print(f"    {t['ticker']} {t.get('name',''):<8}  連買{t['streak']}日  "
                  f"贊助{t.get('sponsorship_score',0):.2f}  {t.get('top_broker','')}×{t.get('top_broker_days',0)}日")

    broken = lead.get("breakdown_cluster") or []
    if broken:
        print(f"\n  ⚠ 假突破叢集 Breakdown Cluster ({len(broken)} 支):")
        for t in broken[:5]:
            print(f"    {t['ticker']} {t.get('name',''):<8}  {t.get('fb_label_zh','')}")

    print(f"\n── 市場敘事 Narrative ──────────────────────────────────────")
    summary_zh = narr.get("summary_zh") or state.get("narrative_zh", "")
    summary_en = narr.get("summary_en") or state.get("narrative_en", "")
    if summary_zh:
        print(f"  ZH: {summary_zh}")
    if summary_en:
        print(f"  EN: {summary_en}")
    bullets_zh = narr.get("bullets_zh") or []
    if bullets_zh:
        print(f"\n  要點:")
        for b in bullets_zh:
            print(f"    • {b}")
    print(f"\n  來源 Source: {narr.get('source','—')}")

    meta = state.get("meta", {})
    if meta:
        print(f"\n  快照數 {meta.get('snapshot_count',0)}  "
              f"時序工具 {'✓' if meta.get('temporal_available') else '✗'}")
    print()


if __name__ == "__main__":
    import json as _json
    import argparse

    # Use the streamlit-free temporal loader (avoids importing viewer which pulls streamlit)
    from tools.temporal._loader import load_index, load_snapshot, real_dates

    dates = real_dates()
    snaps: list[dict] = []
    for d in dates:
        try:
            snaps.append(load_snapshot(d))
        except Exception:
            pass

    if not snaps:
        print("No snapshots found. Run 'make backfill-all' first.")
        sys.exit(1)

    p = argparse.ArgumentParser(description="SCD Market State Engine")
    p.add_argument("--json",  action="store_true", help="Output raw JSON")
    p.add_argument("--layer", choices=["condition", "flow", "leadership", "all"],
                   default="all", help="Which layer to show")
    args = p.parse_args()

    # Always build the full state; --layer only controls what is printed / exported
    result = build(snaps)

    if args.json:
        if args.layer == "condition":
            print(_json.dumps(result["condition"], ensure_ascii=False, indent=2, default=str))
        elif args.layer == "flow":
            print(_json.dumps(result["flow"], ensure_ascii=False, indent=2, default=str))
        elif args.layer == "leadership":
            print(_json.dumps(result["leadership"], ensure_ascii=False, indent=2, default=str))
        else:
            print(_json.dumps(result, ensure_ascii=False, indent=2, default=str))
        sys.exit(0)

    _cli_print(result)
