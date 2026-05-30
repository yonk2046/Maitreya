"""core/intelligence_delta.py — P3h: Market Intelligence Engine

Computes the delta between two consecutive snapshot windows and produces an
immutable DailyIntelligenceReport persisted as:

    reports/YYYY-MM-DD.intelligence.json

Design contract:
  - Generated ONCE per day by the daily pipeline (tools/daily.py).
  - The cockpit reads the saved artifact; it NEVER recomputes at load time.
  - Each report is a self-contained event archive for that trading day.
  - All logic is deterministic — same inputs always produce the same output.

Pipeline position:
    fetch → ingest → archive → [run today + yesterday layers] → delta → save

CLI:
    python3 -m core.intelligence_delta [--date YYYY-MM-DD] [--json] [--force]
    python3 -m core.intelligence_delta --backfill [--force]
    make intelligence [DATE=YYYY-MM-DD]
    make intelligence-backfill
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
from dataclasses import dataclass, field, asdict
from typing import Any

_HERE      = pathlib.Path(__file__).resolve().parent
_AI_STOCK  = _HERE.parent
_REPORTS   = _AI_STOCK / "reports"

if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools.temporal._loader import load_snapshot, real_dates
from core import golden       as _golden
from core import confidence   as _conf
from core import state_machine as _sm

# ─────────────────────────────────────────────────────────────────────────────
# Event type / category / severity constants
# ─────────────────────────────────────────────────────────────────────────────

# Per-ticker events
EVT_STATE_TRANSITION      = "state_transition"
EVT_GOLDEN_ENTRY          = "golden_entry"
EVT_GOLDEN_EXIT           = "golden_exit"
EVT_GOLDEN_TIER_CHANGE    = "golden_tier_change"
EVT_CONFIDENCE_UPGRADE    = "confidence_upgrade"
EVT_CONFIDENCE_DOWNGRADE  = "confidence_downgrade"
EVT_SPONSORSHIP_JUMP      = "sponsorship_jump"
EVT_SPONSORSHIP_COLLAPSE  = "sponsorship_collapse"
EVT_RISK_ELEVATION        = "risk_elevation"
EVT_RISK_REDUCTION        = "risk_reduction"

# Market-level events
EVT_REGIME_SHIFT          = "regime_shift"
EVT_SECTOR_LEADERSHIP     = "sector_leadership_change"
EVT_BREADTH_MILESTONE     = "breadth_milestone"
EVT_TEMPERATURE_CHANGE    = "temperature_change"
EVT_GOLDEN_LIST_EXPANSION = "golden_list_expansion"
EVT_GOLDEN_LIST_CONTRACT  = "golden_list_contraction"

# Categories
CAT_NEW_TODAY        = "new_today"
CAT_UPGRADE          = "upgrade"
CAT_DOWNGRADE        = "downgrade"
CAT_RISK_ALERT       = "risk_alert"
CAT_MARKET_STRUCTURE = "market_structure"

# Severity (ordered low → high)
SEV_INFO     = "info"
SEV_WATCH    = "watch"
SEV_ALERT    = "alert"
SEV_CRITICAL = "critical"

_SEV_RANK = {SEV_INFO: 0, SEV_WATCH: 1, SEV_ALERT: 2, SEV_CRITICAL: 3}

# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DailyEvent:
    """Atomic event record — one row in the event archive."""
    event_type: str
    category:   str
    severity:   str
    zh:         str
    en:         str
    ticker:     str | None  = None
    name:       str | None  = None
    from_value: Any         = None
    to_value:   Any         = None
    delta:      float | None = None


@dataclass
class WatchEntry:
    """A ticker worth monitoring over the next 3–5 sessions."""
    ticker:        str
    name:          str
    reason_zh:     str
    reason_en:     str
    sm_state:      str
    sm_state_zh:   str
    conviction:    float
    confidence:    float
    risk_score:    float
    streak:        int
    sponsorship:   float
    days_in_state: int


@dataclass
class BiggestChange:
    """A single ranked metric change."""
    ticker:     str
    name:       str
    metric:     str
    from_value: float
    to_value:   float
    delta:      float
    direction:  str   # "up" | "down"


@dataclass
class DailyIntelligenceReport:
    """Complete daily intelligence artifact — serialised to intelligence.json."""
    # Identity
    date:           str
    generated_at:   str
    prev_date:      str | None
    snapshot_count: int
    has_prev:       bool

    # Event timeline (5 buckets)
    new_today:        list[DailyEvent]
    upgrades:         list[DailyEvent]
    downgrades:       list[DailyEvent]
    risk_alerts:      list[DailyEvent]
    market_structure: list[DailyEvent]

    # Ranked metric deltas
    biggest_sponsorship_changes: list[BiggestChange]
    biggest_velocity_changes:    list[BiggestChange]
    biggest_confidence_changes:  list[BiggestChange]

    # Forward-looking watch list (from state machine only)
    watch_list: list[WatchEntry]

    # Structured market story (4–6 factual sentences, no prose)
    market_story: list[str]

    # Counts
    total_events:           int = 0
    new_count:              int = 0
    upgrade_count:          int = 0
    downgrade_count:        int = 0
    risk_count:             int = 0
    market_structure_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Internal lookup tables
# ─────────────────────────────────────────────────────────────────────────────

_STATE_RANK: dict[str, int] = {
    "undiscovered":  0,
    "discovered":    1,
    "accumulating":  2,
    "strengthening": 3,
    "confirmed":     4,
    "extended":      5,
    "distributing":  2,   # lateral / deteriorating
    "failed":        1,
    "exited":        0,
}

_STATE_ZH: dict[str, str] = {
    "undiscovered":  "未發現",
    "discovered":    "已發現",
    "accumulating":  "吸籌中",
    "strengthening": "轉強中",
    "confirmed":     "成熟確認",
    "extended":      "持續延伸",
    "distributing":  "疑似出貨",
    "failed":        "訊號失敗",
    "exited":        "已退出",
}

_DOWNGRADE_STATES = {"distributing", "failed", "exited"}
_ALERT_STATES     = {"distributing", "failed"}

_TIER_RANK: dict[str | None, int] = {"PRIME": 3, "STRONG": 2, "QUALIFIED": 1, None: 0}
_TIER_ZH:   dict[str | None, str] = {
    "PRIME": "首選", "STRONG": "強勢", "QUALIFIED": "合格", None: "不在名單",
}

_TEMP_RANK: dict[str, int] = {
    "cool": 0, "stable": 1, "warm": 2, "hot": 3, "extreme": 4,
}

# ─────────────────────────────────────────────────────────────────────────────
# Helper: build lookup maps from layer results
# ─────────────────────────────────────────────────────────────────────────────

def _golden_map(r: "_golden.GoldenResult") -> dict[str, "_golden.GoldenEntry"]:
    return {e.ticker: e for e in r.prime + r.strong + r.qualified}


def _conf_map(r: "_conf.ConfidenceResult") -> dict[str, "_conf.ConfidenceProfile"]:
    return dict(r.profiles)


# ─────────────────────────────────────────────────────────────────────────────
# Diff: State Machine transitions
# ─────────────────────────────────────────────────────────────────────────────

def _diff_states(
    today:     dict[str, "_sm.TickerState"],
    yesterday: dict[str, "_sm.TickerState"] | None,
) -> list[DailyEvent]:
    if yesterday is None:
        return []
    events: list[DailyEvent] = []
    for ticker in sorted(set(today) | set(yesterday)):
        ts = today.get(ticker)
        ys = yesterday.get(ticker)
        if ts is None or ys is None:
            continue
        t_s = ts.state.lower()
        y_s = ys.state.lower()
        if t_s == y_s:
            continue

        t_rank = _STATE_RANK.get(t_s, 0)
        y_rank = _STATE_RANK.get(y_s, 0)
        t_zh   = _STATE_ZH.get(t_s, t_s)
        y_zh   = _STATE_ZH.get(y_s, y_s)

        if t_s in _ALERT_STATES:
            cat = CAT_RISK_ALERT
            sev = SEV_ALERT if t_s == "distributing" else SEV_CRITICAL
        elif t_rank > y_rank:
            cat = CAT_NEW_TODAY if y_s in ("undiscovered", "discovered") else CAT_UPGRADE
            sev = SEV_WATCH
        else:
            cat = CAT_DOWNGRADE
            sev = SEV_WATCH

        events.append(DailyEvent(
            event_type=EVT_STATE_TRANSITION,
            category=cat, severity=sev,
            ticker=ticker, name=ts.name,
            from_value=y_zh, to_value=t_zh,
            zh=f"{ticker} {ts.name}  {y_zh} → {t_zh}",
            en=f"{ticker} {ts.name}  {ys.state} → {ts.state}",
        ))
    return events


# ─────────────────────────────────────────────────────────────────────────────
# Diff: Golden Layer entries / exits / tier changes
# ─────────────────────────────────────────────────────────────────────────────

def _diff_golden(
    today:     dict[str, "_golden.GoldenEntry"],
    yesterday: dict[str, "_golden.GoldenEntry"] | None,
) -> list[DailyEvent]:
    if yesterday is None:
        return []
    events: list[DailyEvent] = []
    for ticker in sorted(set(today) | set(yesterday)):
        te = today.get(ticker)
        ye = yesterday.get(ticker)

        if te and not ye:
            t_zh = _TIER_ZH.get(te.tier, te.tier)
            events.append(DailyEvent(
                event_type=EVT_GOLDEN_ENTRY,
                category=CAT_NEW_TODAY, severity=SEV_WATCH,
                ticker=ticker, name=te.name,
                from_value=None, to_value=te.tier, delta=te.conviction,
                zh=f"{ticker} {te.name}  首次進入黃金名單 [{t_zh}]  信念 {te.conviction:.0%}",
                en=f"{ticker} {te.name}  entered Golden [{te.tier}]  conviction {te.conviction:.0%}",
            ))
        elif not te and ye:
            y_zh = _TIER_ZH.get(ye.tier, ye.tier)
            events.append(DailyEvent(
                event_type=EVT_GOLDEN_EXIT,
                category=CAT_DOWNGRADE, severity=SEV_WATCH,
                ticker=ticker, name=ye.name,
                from_value=ye.tier, to_value=None,
                zh=f"{ticker} {ye.name}  退出黃金名單  (原 {y_zh})",
                en=f"{ticker} {ye.name}  exited Golden  (was {ye.tier})",
            ))
        elif te and ye and te.tier != ye.tier:
            t_rank = _TIER_RANK.get(te.tier, 0)
            y_rank = _TIER_RANK.get(ye.tier, 0)
            is_up  = t_rank > y_rank
            t_zh   = _TIER_ZH.get(te.tier, te.tier)
            y_zh   = _TIER_ZH.get(ye.tier, ye.tier)
            d      = te.conviction - ye.conviction
            events.append(DailyEvent(
                event_type=EVT_GOLDEN_TIER_CHANGE,
                category=CAT_UPGRADE if is_up else CAT_DOWNGRADE,
                severity=SEV_WATCH,
                ticker=ticker, name=te.name,
                from_value=ye.tier, to_value=te.tier, delta=round(d, 3),
                zh=f"{ticker} {te.name}  {y_zh} → {t_zh}  信念 {d:+.0%}",
                en=f"{ticker} {te.name}  {ye.tier} → {te.tier}  conviction {d:+.0%}",
            ))
    return events


# ─────────────────────────────────────────────────────────────────────────────
# Diff: Sponsorship jumps / collapses
# ─────────────────────────────────────────────────────────────────────────────

def _diff_sponsorship(
    today:     dict[str, "_sm.TickerState"],
    yesterday: dict[str, "_sm.TickerState"] | None,
    threshold: float = 0.20,
) -> list[DailyEvent]:
    if yesterday is None:
        return []
    events: list[DailyEvent] = []
    for ticker in sorted(set(today) & set(yesterday)):
        ts = today[ticker]
        ys = yesterday[ticker]
        d  = ts.sponsorship_score - ys.sponsorship_score
        if abs(d) < threshold:
            continue
        if d > 0:
            events.append(DailyEvent(
                event_type=EVT_SPONSORSHIP_JUMP,
                category=CAT_UPGRADE, severity=SEV_WATCH,
                ticker=ticker, name=ts.name,
                from_value=round(ys.sponsorship_score, 3),
                to_value=round(ts.sponsorship_score, 3),
                delta=round(d, 3),
                zh=f"{ticker} {ts.name}  贊助分 {ys.sponsorship_score:.0%} → {ts.sponsorship_score:.0%}  (+{d:.0%})",
                en=f"{ticker} {ts.name}  sponsorship {ys.sponsorship_score:.0%} → {ts.sponsorship_score:.0%}  (+{d:.0%})",
            ))
        else:
            sev = SEV_ALERT if d < -0.35 else SEV_WATCH
            events.append(DailyEvent(
                event_type=EVT_SPONSORSHIP_COLLAPSE,
                category=CAT_RISK_ALERT, severity=sev,
                ticker=ticker, name=ts.name,
                from_value=round(ys.sponsorship_score, 3),
                to_value=round(ts.sponsorship_score, 3),
                delta=round(d, 3),
                zh=f"{ticker} {ts.name}  贊助分崩跌 {ys.sponsorship_score:.0%} → {ts.sponsorship_score:.0%}  ({d:.0%})",
                en=f"{ticker} {ts.name}  sponsorship collapse {ys.sponsorship_score:.0%} → {ts.sponsorship_score:.0%}  ({d:.0%})",
            ))
    return events


# ─────────────────────────────────────────────────────────────────────────────
# Diff: Confidence / Risk profile changes
# ─────────────────────────────────────────────────────────────────────────────

def _diff_confidence(
    today:     dict[str, "_conf.ConfidenceProfile"],
    yesterday: dict[str, "_conf.ConfidenceProfile"] | None,
    threshold: float = 0.15,
) -> list[DailyEvent]:
    if yesterday is None:
        return []
    events: list[DailyEvent] = []
    for ticker in sorted(set(today) & set(yesterday)):
        tp = today[ticker]
        yp = yesterday[ticker]
        cd = tp.confidence - yp.confidence
        rd = tp.risk_score  - yp.risk_score

        if abs(cd) >= threshold:
            events.append(DailyEvent(
                event_type=EVT_CONFIDENCE_UPGRADE if cd > 0 else EVT_CONFIDENCE_DOWNGRADE,
                category=CAT_UPGRADE if cd > 0 else CAT_DOWNGRADE,
                severity=SEV_WATCH,
                ticker=ticker, name=tp.name,
                from_value=round(yp.confidence, 3), to_value=round(tp.confidence, 3),
                delta=round(cd, 3),
                zh=f"{ticker} {tp.name}  信心 {yp.confidence:.0%} → {tp.confidence:.0%}  ({cd:+.0%})",
                en=f"{ticker} {tp.name}  confidence {yp.confidence:.0%} → {tp.confidence:.0%}  ({cd:+.0%})",
            ))

        if rd >= threshold:
            sev = SEV_ALERT if tp.risk_score >= 0.60 else SEV_WATCH
            events.append(DailyEvent(
                event_type=EVT_RISK_ELEVATION,
                category=CAT_RISK_ALERT, severity=sev,
                ticker=ticker, name=tp.name,
                from_value=round(yp.risk_score, 3), to_value=round(tp.risk_score, 3),
                delta=round(rd, 3),
                zh=f"{ticker} {tp.name}  風險上升 {yp.risk_score:.0%} → {tp.risk_score:.0%}  (+{rd:.0%})  {tp.risk_zh}",
                en=f"{ticker} {tp.name}  risk up {yp.risk_score:.0%} → {tp.risk_score:.0%}  (+{rd:.0%})  {tp.risk_level}",
            ))
        elif rd <= -threshold:
            events.append(DailyEvent(
                event_type=EVT_RISK_REDUCTION,
                category=CAT_UPGRADE, severity=SEV_INFO,
                ticker=ticker, name=tp.name,
                from_value=round(yp.risk_score, 3), to_value=round(tp.risk_score, 3),
                delta=round(rd, 3),
                zh=f"{ticker} {tp.name}  風險下降 {yp.risk_score:.0%} → {tp.risk_score:.0%}  ({rd:.0%})",
                en=f"{ticker} {tp.name}  risk reduced {yp.risk_score:.0%} → {tp.risk_score:.0%}  ({rd:.0%})",
            ))
    return events


# ─────────────────────────────────────────────────────────────────────────────
# Diff: Market-level structural changes
# ─────────────────────────────────────────────────────────────────────────────

def _diff_market_structure(
    snaps_today:     list[dict],
    snaps_yesterday: list[dict] | None,
    today_temp:      "_conf.MarketRiskTemperature",
    yest_temp:       "_conf.MarketRiskTemperature | None",
    today_golden_n:  int,
    yest_golden_n:   int | None,
) -> list[DailyEvent]:
    events: list[DailyEvent] = []

    # ── 1. Breadth streak ─────────────────────────────────────────────────
    streak = 0
    for snap in reversed(snaps_today):
        if snap.get("market_regime", {}).get("breadth", 0) >= 0.70:
            streak += 1
        else:
            break
    if streak >= 3:
        sev = SEV_ALERT if streak >= 7 else SEV_WATCH
        events.append(DailyEvent(
            event_type=EVT_BREADTH_MILESTONE,
            category=CAT_MARKET_STRUCTURE, severity=sev,
            from_value=streak, to_value=streak,
            zh=f"市場廣度連續 {streak} 天維持 ≥70%",
            en=f"Market breadth ≥70% for {streak} consecutive days",
        ))

    # ── 2. Sector leadership change ───────────────────────────────────────
    def _top_sector(snaps: list[dict]) -> str | None:
        if not snaps:
            return None
        flows: dict[str, int] = {}
        for s in snaps[-1].get("stocks", []):
            from core.watchlists import stock_group
            grp = stock_group(s.get("ticker", ""))
            flows[grp] = flows.get(grp, 0) + (s.get("main_force_buy") or 0)
        return max(flows, key=flows.get) if flows else None

    t_sector = _top_sector(snaps_today)
    y_sector = _top_sector(snaps_yesterday) if snaps_yesterday else None
    if t_sector and y_sector and t_sector != y_sector:
        from core.watchlists import SECTOR_GROUPS
        t_zh = SECTOR_GROUPS.get(t_sector, {}).get("zh", t_sector)
        y_zh = SECTOR_GROUPS.get(y_sector, {}).get("zh", y_sector)
        events.append(DailyEvent(
            event_type=EVT_SECTOR_LEADERSHIP,
            category=CAT_MARKET_STRUCTURE, severity=SEV_WATCH,
            from_value=y_sector, to_value=t_sector,
            zh=f"板塊資金龍頭：{y_zh} → {t_zh}",
            en=f"Sector leadership: {y_sector} → {t_sector}",
        ))

    # ── 3. Market risk temperature change ────────────────────────────────
    if yest_temp is not None:
        t_rank = _TEMP_RANK.get(today_temp.temperature_level, 1)
        y_rank = _TEMP_RANK.get(yest_temp.temperature_level, 1)
        if t_rank != y_rank:
            direction = "升溫" if t_rank > y_rank else "降溫"
            sev = SEV_ALERT if t_rank >= 3 else SEV_WATCH
            d   = round(today_temp.temperature - yest_temp.temperature, 3)
            events.append(DailyEvent(
                event_type=EVT_TEMPERATURE_CHANGE,
                category=CAT_MARKET_STRUCTURE, severity=sev,
                from_value=yest_temp.temperature_level,
                to_value=today_temp.temperature_level,
                delta=d,
                zh=f"市場溫度{direction}：{yest_temp.temperature_zh} → {today_temp.temperature_zh}  ({d:+.0%})",
                en=f"Temperature {direction}: {yest_temp.temperature_level} → {today_temp.temperature_level}  ({d:+.0%})",
            ))

    # ── 4. Golden list size change ────────────────────────────────────────
    if yest_golden_n is not None:
        dn = today_golden_n - yest_golden_n
        if dn != 0:
            direction = "擴張" if dn > 0 else "收縮"
            evt = EVT_GOLDEN_LIST_EXPANSION if dn > 0 else EVT_GOLDEN_LIST_CONTRACT
            events.append(DailyEvent(
                event_type=evt,
                category=CAT_MARKET_STRUCTURE, severity=SEV_INFO,
                from_value=yest_golden_n, to_value=today_golden_n, delta=float(dn),
                zh=f"黃金名單{direction}：{yest_golden_n} → {today_golden_n} 檔  ({dn:+d})",
                en=f"Golden list {direction}: {yest_golden_n} → {today_golden_n}  ({dn:+d})",
            ))

    return events


# ─────────────────────────────────────────────────────────────────────────────
# Biggest ranked changes (for the "Biggest Changes" section)
# ─────────────────────────────────────────────────────────────────────────────

def _biggest_changes(
    today_sm:   dict[str, "_sm.TickerState"],
    yest_sm:    dict[str, "_sm.TickerState"] | None,
    today_cm:   dict[str, "_conf.ConfidenceProfile"],
    yest_cm:    dict[str, "_conf.ConfidenceProfile"] | None,
    top_n:      int = 5,
) -> tuple[list[BiggestChange], list[BiggestChange], list[BiggestChange]]:
    """Returns (sponsorship_δ, velocity_δ, confidence_δ) — each sorted by |delta| desc."""
    spon: list[BiggestChange] = []
    vel:  list[BiggestChange] = []
    conf: list[BiggestChange] = []

    if yest_sm:
        for ticker in sorted(set(today_sm) & set(yest_sm)):
            ts, ys = today_sm[ticker], yest_sm[ticker]
            ds = ts.sponsorship_score - ys.sponsorship_score
            if abs(ds) > 0.01:
                spon.append(BiggestChange(
                    ticker=ticker, name=ts.name, metric="sponsorship",
                    from_value=round(ys.sponsorship_score, 3),
                    to_value=round(ts.sponsorship_score, 3),
                    delta=round(ds, 3),
                    direction="up" if ds > 0 else "down",
                ))
            tv = ts.velocity_3d or 0.0
            yv = ys.velocity_3d or 0.0
            dv = tv - yv
            if abs(dv) > 50:
                vel.append(BiggestChange(
                    ticker=ticker, name=ts.name, metric="velocity_3d",
                    from_value=round(yv), to_value=round(tv),
                    delta=round(dv),
                    direction="up" if dv > 0 else "down",
                ))

    if yest_cm:
        for ticker in sorted(set(today_cm) & set(yest_cm)):
            tp, yp = today_cm[ticker], yest_cm[ticker]
            dc = tp.confidence - yp.confidence
            if abs(dc) > 0.01:
                conf.append(BiggestChange(
                    ticker=ticker, name=tp.name, metric="confidence",
                    from_value=round(yp.confidence, 3),
                    to_value=round(tp.confidence, 3),
                    delta=round(dc, 3),
                    direction="up" if dc > 0 else "down",
                ))

    spon.sort(key=lambda x: -abs(x.delta))
    vel.sort(key=lambda x: -abs(x.delta))
    conf.sort(key=lambda x: -abs(x.delta))
    return spon[:top_n], vel[:top_n], conf[:top_n]


# ─────────────────────────────────────────────────────────────────────────────
# Watch list — forward-looking, from state machine only
# ─────────────────────────────────────────────────────────────────────────────

_WATCH_STATES = {"strengthening", "accumulating", "confirmed", "extended"}


def _watch_reason(
    ts: "_sm.TickerState",
    cp: "_conf.ConfidenceProfile | None",
) -> tuple[str, str]:
    zh, en = [], []
    s = ts.state.lower()
    if s == "confirmed":
        zh.append(f"成熟確認第 {ts.days_in_state} 天")
        en.append(f"CONFIRMED day {ts.days_in_state}")
    elif s == "strengthening":
        zh.append("轉強中，接近確認門檻")
        en.append("STRENGTHENING — approaching CONFIRMED")
    elif s == "extended":
        zh.append(f"持續延伸第 {ts.days_in_state} 天")
        en.append(f"EXTENDED day {ts.days_in_state}")
    else:
        zh.append("持續吸籌")
        en.append("steady accumulation")
    if ts.sponsorship_score >= 0.60:
        zh.append(f"贊助 {ts.sponsorship_score:.0%}")
        en.append(f"sponsorship {ts.sponsorship_score:.0%}")
    if ts.streak and ts.streak >= 3:
        zh.append(f"連買 {ts.streak} 日")
        en.append(f"streak {ts.streak}d")
    if cp and cp.confidence >= 0.60:
        zh.append(f"信心 {cp.confidence:.0%}")
        en.append(f"confidence {cp.confidence:.0%}")
    return "  ·  ".join(zh), "  ·  ".join(en)


def _build_watch_list(
    today_sm: dict[str, "_sm.TickerState"],
    today_cm: dict[str, "_conf.ConfidenceProfile"],
    top_n:    int = 8,
) -> list[WatchEntry]:
    scored: list[tuple[float, WatchEntry]] = []
    for ticker, ts in today_sm.items():
        if ts.state.lower() not in _WATCH_STATES:
            continue
        cp    = today_cm.get(ticker)
        s     = ts.state.lower()
        score = (
            (0.35 if s == "confirmed"    else
             0.25 if s == "strengthening" else
             0.20 if s == "extended"      else 0.10)
            + ts.sponsorship_score * 0.30
            + min((ts.streak or 0) / 20, 1.0) * 0.20
            + (cp.confidence if cp else 0.0) * 0.15
        )
        reason_zh, reason_en = _watch_reason(ts, cp)
        scored.append((score, WatchEntry(
            ticker=ticker,
            name=ts.name,
            reason_zh=reason_zh,
            reason_en=reason_en,
            sm_state=ts.state,
            sm_state_zh=ts.state_zh,
            conviction=round(cp.golden_conviction if cp else 0.0, 3),
            confidence=round(cp.confidence        if cp else 0.0, 3),
            risk_score=round(cp.risk_score         if cp else 0.0, 3),
            streak=ts.streak or 0,
            sponsorship=round(ts.sponsorship_score, 3),
            days_in_state=ts.days_in_state or 0,
        )))
    scored.sort(key=lambda x: -x[0])
    return [w for _, w in scored[:top_n]]


# ─────────────────────────────────────────────────────────────────────────────
# Market story — 4–6 structured factual sentences
# ─────────────────────────────────────────────────────────────────────────────

def _build_market_story(
    all_events:        list[DailyEvent],
    today_temp:        "_conf.MarketRiskTemperature",
    today_golden_n:    int,
    snaps_today:       list[dict],
) -> list[str]:
    story: list[str] = []

    # 1. Breadth state
    latest_b = snaps_today[-1].get("market_regime", {}).get("breadth", 0) * 100 if snaps_today else 0
    streak = 0
    for snap in reversed(snaps_today):
        if snap.get("market_regime", {}).get("breadth", 0) >= 0.70:
            streak += 1
        else:
            break
    if streak >= 3:
        story.append(f"市場廣度連續 {streak} 天維持 ≥70%（今日 {latest_b:.0f}%）")
    else:
        story.append(f"市場廣度 {latest_b:.0f}%")

    # 2. Temperature
    story.append(f"市場風險溫度：{today_temp.temperature_zh}（{today_temp.temperature:.0%}）")

    # 3. Golden list total
    story.append(f"黃金名單共 {today_golden_n} 檔")

    # 4. Sector leadership change (if any)
    for e in all_events:
        if e.event_type == EVT_SECTOR_LEADERSHIP:
            story.append(e.zh)
            break

    # 5. New CONFIRMED tickers (if any)
    new_conf = [
        e for e in all_events
        if e.event_type == EVT_STATE_TRANSITION
        and isinstance(e.to_value, str) and "確認" in e.to_value
    ]
    if new_conf:
        names = "、".join(f"{e.ticker} {e.name}" for e in new_conf[:3])
        story.append(f"新進入成熟確認：{names}")

    # 6. Distributing alerts (if any)
    dist = [
        e for e in all_events
        if e.event_type == EVT_STATE_TRANSITION
        and isinstance(e.to_value, str) and "出貨" in e.to_value
    ]
    if dist:
        names = "、".join(f"{e.ticker} {e.name}" for e in dist[:3])
        story.append(f"疑似進入出貨：{names}")

    return story


# ─────────────────────────────────────────────────────────────────────────────
# Deserialise from JSON
# ─────────────────────────────────────────────────────────────────────────────

def _from_dict(data: dict) -> DailyIntelligenceReport:
    return DailyIntelligenceReport(
        date=data["date"],
        generated_at=data["generated_at"],
        prev_date=data.get("prev_date"),
        snapshot_count=data["snapshot_count"],
        has_prev=data["has_prev"],
        new_today=       [DailyEvent(**e)    for e in data.get("new_today", [])],
        upgrades=        [DailyEvent(**e)    for e in data.get("upgrades", [])],
        downgrades=      [DailyEvent(**e)    for e in data.get("downgrades", [])],
        risk_alerts=     [DailyEvent(**e)    for e in data.get("risk_alerts", [])],
        market_structure=[DailyEvent(**e)    for e in data.get("market_structure", [])],
        biggest_sponsorship_changes=[BiggestChange(**e) for e in data.get("biggest_sponsorship_changes", [])],
        biggest_velocity_changes=   [BiggestChange(**e) for e in data.get("biggest_velocity_changes", [])],
        biggest_confidence_changes= [BiggestChange(**e) for e in data.get("biggest_confidence_changes", [])],
        watch_list=  [WatchEntry(**e) for e in data.get("watch_list", [])],
        market_story=data.get("market_story", []),
        total_events=          data.get("total_events", 0),
        new_count=             data.get("new_count", 0),
        upgrade_count=         data.get("upgrade_count", 0),
        downgrade_count=       data.get("downgrade_count", 0),
        risk_count=            data.get("risk_count", 0),
        market_structure_count=data.get("market_structure_count", 0),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API: generate / load / latest
# ─────────────────────────────────────────────────────────────────────────────

def generate(date: str | None = None, force: bool = False) -> DailyIntelligenceReport:
    """
    Generate (or load cached) DailyIntelligenceReport for `date` (default: latest).
    Saves result to reports/YYYY-MM-DD.intelligence.json.
    Pass force=True to regenerate even if the file already exists.
    """
    dates = real_dates()
    if not dates:
        raise RuntimeError("No snapshot dates found in reports/.")

    if date is None:
        date = dates[-1]
    elif date not in dates:
        raise ValueError(f"Date {date!r} not in snapshot archive.")

    out_path = _REPORTS / f"{date}.intelligence.json"
    if out_path.exists() and not force:
        return _from_dict(json.loads(out_path.read_text(encoding="utf-8")))

    # ── Load snapshot windows ─────────────────────────────────────────────
    all_dates   = [d for d in dates if d <= date]
    snaps_today = [load_snapshot(d) for d in all_dates]

    prev_date:   str | None   = None
    snaps_prev:  list[dict] | None = None
    idx = dates.index(date)
    if idx > 0:
        prev_date  = dates[idx - 1]
        snaps_prev = [load_snapshot(d) for d in dates if d <= prev_date]

    # ── Run all layers — today ────────────────────────────────────────────
    t_golden  = _golden.run(snaps_today)
    t_conf    = _conf.run(snaps_today)
    t_sm      = _sm.run_all(snaps_today)
    t_gm      = _golden_map(t_golden)
    t_cm      = _conf_map(t_conf)

    # ── Run all layers — yesterday ────────────────────────────────────────
    y_sm: dict | None = None
    y_gm: dict | None = None
    y_cm: dict | None = None
    y_temp = None
    y_golden_n: int | None = None

    if snaps_prev:
        y_golden  = _golden.run(snaps_prev)
        y_conf    = _conf.run(snaps_prev)
        y_sm      = _sm.run_all(snaps_prev)
        y_gm      = _golden_map(y_golden)
        y_cm      = _conf_map(y_conf)
        y_temp    = y_conf.market_temperature
        y_golden_n = len(y_gm)

    t_golden_n = len(t_gm)

    # ── Compute all diffs ─────────────────────────────────────────────────
    all_events: list[DailyEvent] = (
        _diff_states(t_sm, y_sm)
        + _diff_golden(t_gm, y_gm)
        + _diff_sponsorship(t_sm, y_sm)
        + _diff_confidence(t_cm, y_cm)
        + _diff_market_structure(
            snaps_today, snaps_prev,
            t_conf.market_temperature, y_temp,
            t_golden_n, y_golden_n,
        )
    )

    # ── Bucket by category ────────────────────────────────────────────────
    new_today   = [e for e in all_events if e.category == CAT_NEW_TODAY]
    upgrades    = [e for e in all_events if e.category == CAT_UPGRADE]
    downgrades  = [e for e in all_events if e.category == CAT_DOWNGRADE]
    risk_alerts = sorted(
        [e for e in all_events if e.category == CAT_RISK_ALERT],
        key=lambda e: -_SEV_RANK.get(e.severity, 0),
    )
    mkt_struct  = [e for e in all_events if e.category == CAT_MARKET_STRUCTURE]

    # ── Ranked changes ────────────────────────────────────────────────────
    spon_bc, vel_bc, conf_bc = _biggest_changes(t_sm, y_sm, t_cm, y_cm)

    # ── Watch list + market story ─────────────────────────────────────────
    watch_list   = _build_watch_list(t_sm, t_cm)
    market_story = _build_market_story(all_events, t_conf.market_temperature, t_golden_n, snaps_today)

    report = DailyIntelligenceReport(
        date=date,
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
        prev_date=prev_date,
        snapshot_count=len(snaps_today),
        has_prev=snaps_prev is not None,
        new_today=new_today,
        upgrades=upgrades,
        downgrades=downgrades,
        risk_alerts=risk_alerts,
        market_structure=mkt_struct,
        biggest_sponsorship_changes=spon_bc,
        biggest_velocity_changes=vel_bc,
        biggest_confidence_changes=conf_bc,
        watch_list=watch_list,
        market_story=market_story,
        total_events=len(all_events),
        new_count=len(new_today),
        upgrade_count=len(upgrades),
        downgrade_count=len(downgrades),
        risk_count=len(risk_alerts),
        market_structure_count=len(mkt_struct),
    )

    # ── Persist ───────────────────────────────────────────────────────────
    out_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def load_for_date(date: str) -> DailyIntelligenceReport | None:
    """Load a persisted intelligence report for `date`. Returns None if not found."""
    path = _REPORTS / f"{date}.intelligence.json"
    if not path.exists():
        return None
    return _from_dict(json.loads(path.read_text(encoding="utf-8")))


def latest_available() -> DailyIntelligenceReport | None:
    """Load the most recent persisted intelligence report."""
    files = sorted(_REPORTS.glob("*.intelligence.json"))
    return _from_dict(json.loads(files[-1].read_text(encoding="utf-8"))) if files else None


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="P3h Market Intelligence Engine")
    ap.add_argument("--date",      default=None,  help="YYYY-MM-DD (default: latest)")
    ap.add_argument("--json",      action="store_true")
    ap.add_argument("--force",     action="store_true", help="Regenerate even if file exists")
    ap.add_argument("--backfill",  action="store_true", help="Generate for all dates missing intelligence.json")
    args = ap.parse_args()

    _SEV_ICON = {SEV_CRITICAL: "🔴", SEV_ALERT: "🟠", SEV_WATCH: "🟡", SEV_INFO: "⚪"}

    if args.backfill:
        dates = real_dates()
        for d in dates:
            path = _REPORTS / f"{d}.intelligence.json"
            if not path.exists() or args.force:
                print(f"  {d} … ", end="", flush=True)
                try:
                    r = generate(d, force=args.force)
                    print(f"✓  {r.total_events} events")
                except Exception as exc:
                    print(f"✗  {exc}")
            else:
                print(f"  {d}   already exists, skip (use --force to regenerate)")
        sys.exit(0)

    report = generate(args.date, force=args.force)

    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        sys.exit(0)

    # ── Human-readable summary ────────────────────────────────────────────
    W = 60
    print(f"\n{'='*W}")
    print(f"  ◈ SCD Market Intelligence  {report.date}")
    print(f"  vs {report.prev_date or '—'}  ·  {report.snapshot_count} snapshots  ·  {report.total_events} events")
    print(f"{'='*W}\n")

    print("── 市場故事 Market Story ──")
    for s in report.market_story:
        print(f"  • {s}")

    if report.new_today:
        print(f"\n── 今日新增 What's New  ({report.new_count}) ──")
        for e in report.new_today:
            print(f"  + {e.zh}")

    if report.upgrades:
        print(f"\n── 升級 Upgrades  ({report.upgrade_count}) ──")
        for e in report.upgrades:
            print(f"  ↑ {e.zh}")

    if report.downgrades:
        print(f"\n── 降級 Downgrades  ({report.downgrade_count}) ──")
        for e in report.downgrades:
            print(f"  ↓ {e.zh}")

    if report.risk_alerts:
        print(f"\n── 風險警報 Risk Alerts  ({report.risk_count}) ──")
        for e in report.risk_alerts:
            print(f"  {_SEV_ICON.get(e.severity,'●')} {e.zh}")

    if report.market_structure:
        print(f"\n── 市場結構 Market Structure  ({report.market_structure_count}) ──")
        for e in report.market_structure:
            print(f"  ◆ {e.zh}")

    if report.biggest_sponsorship_changes:
        print(f"\n── 贊助變化排行 Sponsorship Δ ──")
        for c in report.biggest_sponsorship_changes:
            arrow = "↑" if c.direction == "up" else "↓"
            print(f"  {arrow} {c.ticker} {c.name:<8}  {c.from_value:.0%} → {c.to_value:.0%}  ({c.delta:+.0%})")

    if report.biggest_velocity_changes:
        print(f"\n── 速度變化排行 Velocity Δ ──")
        for c in report.biggest_velocity_changes:
            arrow = "↑" if c.direction == "up" else "↓"
            print(f"  {arrow} {c.ticker} {c.name:<8}  {c.from_value:+,.0f} → {c.to_value:+,.0f}張/日  ({c.delta:+,.0f})")

    if report.biggest_confidence_changes:
        print(f"\n── 信心變化排行 Confidence Δ ──")
        for c in report.biggest_confidence_changes:
            arrow = "↑" if c.direction == "up" else "↓"
            print(f"  {arrow} {c.ticker} {c.name:<8}  {c.from_value:.0%} → {c.to_value:.0%}  ({c.delta:+.0%})")

    if report.watch_list:
        print(f"\n── 持續觀察 Watch List  ({len(report.watch_list)}) ──")
        for w in report.watch_list:
            print(f"  ◉ {w.ticker} {w.name:<8}  [{w.sm_state_zh}]  {w.reason_zh}")

    print(f"\n  已儲存 → reports/{report.date}.intelligence.json")
    print(f"  合計 {report.total_events} 個事件\n")
