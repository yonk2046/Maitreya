"""SCD Engine — Narrative Engine  (P3c-Narrative)

Pure translation layer: converts existing temporal metric outputs into
human-readable market intelligence.

This module ONLY interprets. It does NOT:
  - compute new signals
  - assign scores or tiers
  - make predictions or trading recommendations
  - access any data source directly (all inputs passed in by caller)

Consumes outputs from:
  - tools.temporal.regime_monitor      (SnapshotObservation, WindowDelta)
  - tools.temporal.streak_analyzer     (StreakRow)
  - tools.temporal.transition_detector (Transition, reappearance_events)
  - tools.temporal.persistence_ranker  (PersistenceRow, mode=composite)
  - core.market_context                (regime_shift, leadership_rotation,
                                        accumulation_velocity,
                                        failed_breakout_memory)

Output structure (all returned as plain dicts for JSON-serializability):
  NarrativeReport = {
    "generated_at":    str,
    "date_range":      [first_date, last_date],
    "latest_date":     str,
    "market_narrative": [{"zh": str, "en": str}, ...],   # 3–6 bullets
    "key_themes": {
        "sector_rotation":      {"zh": str, "en": str},
        "capital_flow":         {"zh": str, "en": str},
        "strength_vs_weakness": {"zh": str, "en": str},
    },
    "notable_entities": {
        "persistent_tickers":    [{"ticker": str, "note_zh": str, "note_en": str}, ...],
        "strongest_transitions": [{"ticker": str, "event": str, "date": str,
                                   "note_zh": str, "note_en": str}, ...],
        "possible_false_breakouts": [{"ticker": str, "breakout_date": str,
                                      "note_zh": str, "note_en": str}, ...],
    },
  }

CLI:
    python -m core.narrative_engine
    python -m core.narrative_engine --json
    python -m core.narrative_engine --dates 20
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date
from typing import Any

# ---------------------------------------------------------------------------
# Lazy imports — avoid circular at module level; callers supply pre-computed
# dicts when embedding in cockpit, but the CLI convenience function calls
# these itself.
# ---------------------------------------------------------------------------

def _load_all_inputs(lookback: int = 10) -> dict[str, Any]:
    """Convenience loader used by CLI and generate(). Returns raw metric dicts."""
    from tools.temporal.regime_monitor import observe_all, deltas
    from tools.temporal.streak_analyzer import analyze as streak_analyze
    from tools.temporal.transition_detector import detect, reappearance_events
    from tools.temporal.persistence_ranker import rank
    from tools.temporal._loader import real_dates, load_snapshot
    from core.market_context import (
        regime_shift, leadership_rotation,
        accumulation_velocity, failed_breakout_memory,
    )
    from dataclasses import asdict

    dates = real_dates()[-lookback:]
    if not dates:
        return {}

    snaps = [load_snapshot(d) for d in dates]

    # Regime + leadership from market_context (richer than regime_monitor alone)
    regime  = regime_shift(snaps)
    rot     = leadership_rotation(snaps)

    # Per-ticker context for failed-breakout detection
    all_tickers: set[str] = set()
    for snap in snaps:
        for s in snap.get("stocks", []):
            all_tickers.add(s.get("ticker", ""))
    all_tickers.discard("")

    def _recs(ticker: str) -> list[dict[str, Any]]:
        rows = []
        for snap in snaps:
            rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
            rows.append({
                "date":           snap.get("date", "?"),
                "main_force_buy": rec.get("main_force_buy")  if rec else None,
                "volume":         rec.get("volume")           if rec else None,
                "change_pct":     rec.get("change_pct")       if rec else None,
                "current_price":  rec.get("current_price")    if rec else None,
                "top5_branches":  rec.get("top5_branches")    if rec else [],
                "present":        rec is not None,
            })
        return rows

    fb_results = {t: failed_breakout_memory(t, _recs(t)) for t in sorted(all_tickers)}
    acc_results = {t: accumulation_velocity(t, _recs(t)) for t in sorted(all_tickers)}

    obs_all   = [asdict(o) for o in observe_all()]
    delta_all = [asdict(d) for d in deltas()]
    streak_rows = [asdict(r) for r in streak_analyze()]
    trans_rows  = [asdict(t) for t in detect()]
    reappear    = [asdict(t) for t in reappearance_events()]
    persist_rows = [asdict(r) for r in rank(mode="composite")]

    # Build name map from all loaded snapshots so descriptions use full names
    from core.watchlists import build_name_map
    name_map = build_name_map(snaps)

    return {
        "dates":        dates,
        "observations": obs_all,
        "deltas":       delta_all,
        "streak_rows":  streak_rows,
        "transitions":  trans_rows,
        "reappearances": reappear,
        "persist_rows": persist_rows,
        "regime":       regime,
        "leadership":   rot,
        "failed_breakouts": fb_results,
        "accumulation": acc_results,
        "name_map": name_map,
    }


# ---------------------------------------------------------------------------
# Threshold helpers (purely structural, no alpha claims)
# ---------------------------------------------------------------------------

def _breadth_label(b: float) -> tuple[str, str]:
    """Descriptive label for breadth percentage (0–1). Returns (zh, en)."""
    if b >= 0.80:
        return ("多數個股上漲", "majority of stocks advancing")
    if b >= 0.55:
        return ("略多個股上漲", "more stocks advancing than declining")
    if b >= 0.45:
        return ("漲跌接近均衡", "advances and declines roughly balanced")
    if b >= 0.20:
        return ("略多個股下跌", "more stocks declining than advancing")
    return ("多數個股下跌", "majority of stocks declining")


def _chg_label(c: float) -> tuple[str, str]:
    """Descriptive label for mean change_pct. Returns (zh, en)."""
    if c >= 3.0:
        return ("平均漲幅顯著擴大", "average gains notably extended")
    if c >= 1.0:
        return ("平均呈現溫和上漲", "average showing moderate gains")
    if c >= -1.0:
        return ("整體漲跌幅度有限", "overall price movement limited")
    if c >= -3.0:
        return ("平均呈現溫和回落", "average showing moderate pullback")
    return ("平均跌幅明顯擴大", "average declines notably extended")


def _carry_label(r: float) -> tuple[str, str]:
    if r >= 0.85:
        return ("連續留存率高", "high carry-over continuity")
    if r >= 0.60:
        return ("留存率中等", "moderate carry-over rate")
    return ("宇宙輪換明顯", "significant universe rotation")


def _streak_label(s: int) -> tuple[str, str]:
    if s >= 5:
        return ("連續出現≥5日", f"present ≥5 consecutive days")
    if s >= 3:
        return ("連續出現3–4日", f"present 3–4 consecutive days")
    if s >= 2:
        return ("連續出現2日", "present 2 consecutive days")
    return ("連續出現1日", "present today only")


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_market_narrative(inputs: dict[str, Any]) -> list[dict[str, str]]:
    """Return 3–6 bilingual bullet sentences describing the current market state."""
    bullets: list[dict[str, str]] = []
    obs   = inputs.get("observations", [])
    delts = inputs.get("deltas", [])
    regime = inputs.get("regime", {})

    if not obs:
        return [{"zh": "尚無足夠快照資料", "en": "Insufficient snapshot data available."}]

    latest = obs[-1]
    prev   = obs[-2] if len(obs) >= 2 else None
    latest_delta = delts[-1] if delts else None

    # ── Bullet 1: Universe size & breadth ────────────────────────────────
    univ   = latest.get("universe_size", 0)
    bdpos  = latest.get("breadth_positive")
    if bdpos is not None:
        zh_b, en_b = _breadth_label(bdpos)
        bullets.append({
            "zh": f"掃描宇宙共 {univ} 支個股，上漲廣度 {bdpos*100:.1f}%，{zh_b}。",
            "en": f"Scanning universe covers {univ} stocks; advance breadth at {bdpos*100:.1f}% — {en_b}.",
        })
    else:
        bullets.append({
            "zh": f"掃描宇宙共 {univ} 支個股，本日漲跌資料不完整。",
            "en": f"Scanning universe covers {univ} stocks; advance/decline data incomplete for this date.",
        })

    # ── Bullet 2: Mean price change ───────────────────────────────────────
    mean_chg = latest.get("mean_change_pct")
    if mean_chg is not None:
        zh_c, en_c = _chg_label(mean_chg)
        sign = "+" if mean_chg >= 0 else ""
        bullets.append({
            "zh": f"個股平均漲跌幅為 {sign}{mean_chg:.2f}%，{zh_c}。",
            "en": f"Average stock move: {sign}{mean_chg:.2f}%. {en_c.capitalize()}.",
        })

    # ── Bullet 3: Breadth trend vs prior day ─────────────────────────────
    if latest_delta is not None:
        bd_delta = latest_delta.get("breadth_positive_delta")
        new_in   = latest_delta.get("new_entrants_count", 0)
        lost     = latest_delta.get("leavers_count", 0)
        carry    = latest_delta.get("carry_rate", 1.0)
        zh_carry, en_carry = _carry_label(carry)

        if bd_delta is not None:
            direction_zh = "擴大" if bd_delta > 0.02 else ("縮小" if bd_delta < -0.02 else "維持穩定")
            direction_en = "widened" if bd_delta > 0.02 else ("narrowed" if bd_delta < -0.02 else "held steady")
            bullets.append({
                "zh": (f"相較前日，上漲廣度{direction_zh} {abs(bd_delta)*100:.1f}ppt；"
                       f"新進 {new_in} 支、離開 {lost} 支，{zh_carry}（留存率 {carry*100:.0f}%）。"),
                "en": (f"Advance breadth {direction_en} by {abs(bd_delta)*100:.1f}ppt vs. prior day; "
                       f"{new_in} new entrants, {lost} exits — {en_carry} (carry rate {carry*100:.0f}%)."),
            })

    # ── Bullet 4: Regime label (from market_context.regime_shift) ────────
    regime_label_zh = regime.get("regime_label_zh", "")
    regime_label_en = regime.get("regime_label_en", "")
    breadth_trend   = regime.get("breadth_trend", "")
    if regime_label_zh:
        trend_map = {
            "rising":   ("上升", "rising"),
            "falling":  ("下降", "declining"),
            "stable":   ("平穩", "stable"),
            "volatile": ("震盪", "volatile"),
        }
        t_zh, t_en = trend_map.get(breadth_trend, (breadth_trend, breadth_trend))
        bullets.append({
            "zh": f"整體市場體制觀察：{regime_label_zh}；廣度走勢{t_zh}。",
            "en": f"Market regime observation: {regime_label_en}. Breadth trend: {t_en}.",
        })
        if regime.get("transition_detected"):
            note = regime.get("transition_note", "")
            bullets.append({
                "zh": f"⚡ 體制轉換偵測：{note}",
                "en": f"⚡ Regime transition detected: {note}",
            })

    # ── Bullet 5: Main force data coverage ───────────────────────────────
    mfb_known = latest.get("main_force_buy_known", 0)
    top5_cov  = latest.get("top5_branch_coverage", 0)
    if mfb_known > 0 or top5_cov > 0:
        bullets.append({
            "zh": (f"主力買賣超資料覆蓋率 {mfb_known*100:.0f}%，"
                   f"分點資料覆蓋率 {top5_cov*100:.0f}%。"),
            "en": (f"Main-force buy data available for {mfb_known*100:.0f}% of universe; "
                   f"branch breakdown available for {top5_cov*100:.0f}%."),
        })

    return bullets[:6]  # cap at 6


def _build_key_themes(inputs: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return sector rotation, capital flow, and strength/weakness themes."""
    from core.watchlists import TIER_A
    rot         = inputs.get("leadership", {})
    acc_results = inputs.get("accumulation", {})
    persist_rows = inputs.get("persist_rows", [])
    streak_rows  = inputs.get("streak_rows", [])
    name_map     = inputs.get("name_map", {})

    def _nm(t: str) -> str:
        return name_map.get(t) or TIER_A.get(t, {}).get("name", t)

    # ── Theme 1: Sector rotation ─────────────────────────────────────────
    leading_zh = rot.get("leading_label_zh", "—")
    leading_en = rot.get("leading_label_en", "—")
    if rot.get("rotation_detected"):
        from_s = rot.get("rotation_from", "—")
        to_s   = rot.get("rotation_to", "—")
        sector_rot_zh = f"資金輪動偵測：資金從 {from_s} 移向 {to_s}；目前領漲板塊為{leading_zh}。"
        sector_rot_en = f"Sector rotation detected: capital shifted from {from_s} to {to_s}. Current leading sector: {leading_en}."
    else:
        ranked = rot.get("ranked_sectors", [])
        flows  = rot.get("sector_flows", {})
        if ranked and flows:
            top2 = ranked[:2]
            top_names_zh = "、".join(flows[s]["label_zh"] for s in top2 if s in flows)
            top_names_en = " and ".join(flows[s]["label_en"] for s in top2 if s in flows)
            sector_rot_zh = f"板塊資金流向集中於{top_names_zh}，無明顯輪動訊號。"
            sector_rot_en = f"Capital flow concentrated in {top_names_en}; no clear rotation signal."
        else:
            sector_rot_zh = f"目前領漲板塊為{leading_zh}，板塊分佈資料尚不完整。"
            sector_rot_en = f"Leading sector observed: {leading_en}. Sector distribution data incomplete."

    # ── Theme 2: Capital flow direction ──────────────────────────────────
    # Use accumulation_velocity data: how many tickers in net-buy streak
    buy_streak_tickers = [t for t, a in acc_results.items() if a.get("streak", 0) >= 2]
    sell_streak_tickers = [t for t, a in acc_results.items() if a.get("streak", 0) <= -2]
    n_buy  = len(buy_streak_tickers)
    n_sell = len(sell_streak_tickers)

    if n_buy > n_sell * 2:
        cap_zh = f"累積資金流向偏多，{n_buy} 支個股出現連續2日以上淨買超，{n_sell} 支呈現淨賣超。"
        cap_en = f"Capital flow skewed toward accumulation: {n_buy} stocks showing net-buy streaks ≥2 days vs. {n_sell} in net-sell streaks."
    elif n_sell > n_buy * 2:
        cap_zh = f"累積資金流向偏空，{n_sell} 支個股出現連續2日以上淨賣超，{n_buy} 支呈現淨買超。"
        cap_en = f"Capital flow skewed toward distribution: {n_sell} stocks in net-sell streaks ≥2 days vs. {n_buy} in net-buy streaks."
    elif n_buy == 0 and n_sell == 0:
        cap_zh = "目前無個股呈現連續2日以上的明確籌碼方向。"
        cap_en = "No stocks currently showing clear directional streaks of ≥2 consecutive days."
    else:
        cap_zh = f"資金方向分歧：{n_buy} 支連續買超 vs. {n_sell} 支連續賣超，整體偏向中性。"
        cap_en = f"Mixed capital direction: {n_buy} stocks in accumulation streaks vs. {n_sell} in distribution — overall neutral."

    # ── Theme 3: Strength vs weakness ────────────────────────────────────
    # Top persistent (by composite) vs lowest streak_stability
    strong = persist_rows[:3] if persist_rows else []
    weak   = sorted(streak_rows, key=lambda r: r.get("streak_stability", 1.0))[:3] if streak_rows else []

    def _disp(t: str) -> str:
        n = _nm(t)
        return f"{t} {n}" if n != t else t

    strong_names = "、".join(_disp(r["ticker"]) for r in strong)
    strong_en    = ", ".join(_disp(r["ticker"]) for r in strong)
    weak_names   = "、".join(_disp(r["ticker"]) for r in weak)
    weak_en      = ", ".join(_disp(r["ticker"]) for r in weak)

    if strong_names and weak_names:
        sv_zh = f"時序延續性最強個股：{strong_names}；出現頻率最不規則的個股：{weak_names}。"
        sv_en = f"Highest temporal persistence: {strong_en}. Most irregular presence patterns: {weak_en}."
    elif strong_names:
        sv_zh = f"時序延續性最強個股：{strong_names}。"
        sv_en = f"Highest temporal persistence observed: {strong_en}."
    else:
        sv_zh = "延續性資料尚不足以做強弱比較。"
        sv_en = "Insufficient persistence data to contrast strength and weakness."

    return {
        "sector_rotation":      {"zh": sector_rot_zh,  "en": sector_rot_en},
        "capital_flow":         {"zh": cap_zh,          "en": cap_en},
        "strength_vs_weakness": {"zh": sv_zh,           "en": sv_en},
    }


def _build_notable_entities(inputs: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return top persistent tickers, strongest transitions, and possible false breakouts."""
    from core.watchlists import TIER_A

    persist_rows  = inputs.get("persist_rows", [])
    reappear      = inputs.get("reappearances", [])
    fb_results    = inputs.get("failed_breakouts", {})
    acc_results   = inputs.get("accumulation", {})
    dates         = inputs.get("dates", [])
    name_map      = inputs.get("name_map", {})

    def _nm(ticker: str) -> str:
        """Return company name, preferring name_map over TIER_A."""
        return name_map.get(ticker) or TIER_A.get(ticker, {}).get("name", ticker)

    # ── 1. Top persistent tickers (composite rank, top 5) ───────────────
    persistent: list[dict[str, Any]] = []
    for row in persist_rows[:5]:
        t    = row["ticker"]
        name = _nm(t)
        cur  = row.get("current_streak", 0)
        cov  = row.get("coverage", 0)
        zh_s, en_s = _streak_label(cur)
        persistent.append({
            "ticker":   t,
            "name":     name,
            "current_streak": cur,
            "coverage_pct":   round(cov * 100, 1),
            "note_zh": f"{name}（{t}）：覆蓋率 {cov*100:.0f}%，{zh_s}。",
            "note_en": f"{name} ({t}): {cov*100:.0f}% date coverage, {en_s}.",
        })

    # ── 2. Strongest transitions (recent ENTER / REAPPEAR, last 5 events) ─
    recent_reappear = sorted(
        [r for r in reappear if r.get("notes", "").startswith("REAPPEAR")],
        key=lambda r: r.get("date", ""), reverse=True,
    )[:5]
    recent_enter = sorted(
        [r for r in reappear if r.get("notes") == "ENTER"],
        key=lambda r: r.get("date", ""), reverse=True,
    )[:3]

    transitions: list[dict[str, Any]] = []
    for ev in (recent_reappear + recent_enter)[:6]:
        t    = ev.get("ticker", "")
        note = ev.get("notes", "")
        d    = ev.get("date", "")
        name = _nm(t)
        acc  = acc_results.get(t, {})
        streak = acc.get("streak", 0)

        if note.startswith("REAPPEAR"):
            absent_days = note.split("_after_")[-1].replace("d", "") if "_after_" in note else "?"
            zh_n = f"{name}（{t}）在 {d} 重新出現，此前缺席 {absent_days} 日"
            en_n = f"{name} ({t}) re-entered the universe on {d} after {absent_days} absent days"
        else:
            zh_n = f"{name}（{t}）於 {d} 首次出現在掃描宇宙"
            en_n = f"{name} ({t}) first appeared in scanning universe on {d}"

        if streak >= 2:
            zh_n += f"，目前連續主力買超 {streak} 日。"
            en_n += f"; currently {streak} consecutive days of net buying."
        else:
            zh_n += "。"
            en_n += "."

        transitions.append({
            "ticker": t,
            "name":   name,
            "event":  note,
            "date":   d,
            "note_zh": zh_n,
            "note_en": en_n,
        })

    # ── 3. Possible false breakouts ───────────────────────────────────────
    false_bos: list[dict[str, Any]] = []
    for t, fb in fb_results.items():
        if not fb.get("failed_breakout_detected"):
            continue
        name  = _nm(t)
        bd    = fb.get("breakout_date", "?")
        bchg  = fb.get("breakout_chg", 0)
        vrat  = fb.get("vol_ratio", 0)
        ret   = fb.get("retreat_days", 0)
        false_bos.append({
            "ticker":        t,
            "name":          name,
            "breakout_date": bd,
            "breakout_chg":  bchg,
            "vol_ratio":     vrat,
            "retreat_days":  ret,
            "note_zh": (
                f"{name}（{t}）於 {bd} 出現量增 {vrat:.1f}× 且漲幅 +{bchg:.1f}% 的突破訊號，"
                f"隨後連續 {ret} 日回落，可能為假突破。"
            ),
            "note_en": (
                f"{name} ({t}) showed a breakout signal on {bd} "
                f"({vrat:.1f}× volume, +{bchg:.1f}% gain), "
                f"followed by {ret} consecutive days of retreat — possible failed breakout."
            ),
        })

    # Sort false breakouts by most recent
    false_bos.sort(key=lambda x: x.get("breakout_date", ""), reverse=True)

    return {
        "persistent_tickers":    persistent,
        "strongest_transitions": transitions,
        "possible_false_breakouts": false_bos,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate(
    lookback: int = 10,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a NarrativeReport dict.

    Args:
        lookback: How many recent dates to include when loading inputs
                  automatically. Ignored if `inputs` is supplied.
        inputs:   Pre-computed dict from _load_all_inputs(). Pass this when
                  the caller (e.g. cockpit.py) has already loaded metrics to
                  avoid redundant disk reads.

    Returns:
        NarrativeReport dict — safe to pass to json.dumps().
    """
    if inputs is None:
        inputs = _load_all_inputs(lookback)

    if not inputs:
        return {
            "generated_at": str(_date.today()),
            "date_range": [],
            "latest_date": "",
            "market_narrative": [{"zh": "無快照資料", "en": "No snapshot data available."}],
            "key_themes": {
                "sector_rotation":      {"zh": "—", "en": "—"},
                "capital_flow":         {"zh": "—", "en": "—"},
                "strength_vs_weakness": {"zh": "—", "en": "—"},
            },
            "notable_entities": {
                "persistent_tickers":    [],
                "strongest_transitions": [],
                "possible_false_breakouts": [],
            },
        }

    dates = inputs.get("dates", [])

    return {
        "generated_at": str(_date.today()),
        "date_range":   [dates[0], dates[-1]] if dates else [],
        "latest_date":  dates[-1] if dates else "",
        "market_narrative":  _build_market_narrative(inputs),
        "key_themes":        _build_key_themes(inputs),
        "notable_entities":  _build_notable_entities(inputs),
    }


# ---------------------------------------------------------------------------
# Terminal printer
# ---------------------------------------------------------------------------

def _print_report(report: dict[str, Any]) -> None:
    dr = report.get("date_range", [])
    ld = report.get("latest_date", "?")
    dr_str = f"{dr[0]} → {dr[-1]}" if len(dr) == 2 else ld

    print()
    print("=" * 64)
    print(f"  SCD 市場敘事  Market Narrative   ({dr_str})")
    print("=" * 64)

    for i, bullet in enumerate(report.get("market_narrative", []), 1):
        print(f"  {i}. {bullet['zh']}")
        print(f"     {bullet['en']}")
        print()

    print("─" * 64)
    print("  主題  Key Themes")
    print("─" * 64)
    themes = report.get("key_themes", {})
    for key_en, label_zh in [
        ("sector_rotation",      "板塊輪動"),
        ("capital_flow",         "資金方向"),
        ("strength_vs_weakness", "強弱對比"),
    ]:
        t = themes.get(key_en, {})
        print(f"  [{label_zh}]")
        print(f"    {t.get('zh', '')}")
        print(f"    {t.get('en', '')}")
        print()

    ent = report.get("notable_entities", {})

    # Persistent tickers
    pers = ent.get("persistent_tickers", [])
    if pers:
        print("─" * 64)
        print("  持續出現個股  Persistent Tickers")
        print("─" * 64)
        for e in pers:
            print(f"  • {e['note_zh']}")
            print(f"    {e['note_en']}")
        print()

    # Transitions
    trans = ent.get("strongest_transitions", [])
    if trans:
        print("─" * 64)
        print("  重要轉換  Notable Transitions")
        print("─" * 64)
        for e in trans:
            print(f"  • {e['note_zh']}")
            print(f"    {e['note_en']}")
        print()

    # False breakouts
    fbs = ent.get("possible_false_breakouts", [])
    if fbs:
        print("─" * 64)
        print("  可能假突破  Possible False Breakouts")
        print("─" * 64)
        for e in fbs:
            print(f"  ⚠ {e['note_zh']}")
            print(f"    {e['note_en']}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="SCD Narrative Engine — metrics → bilingual market intelligence"
    )
    ap.add_argument(
        "--dates", type=int, default=10,
        help="lookback window in trading days (default: 10)",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="emit JSON to stdout instead of formatted text",
    )
    args = ap.parse_args(argv)

    report = generate(lookback=args.dates)

    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        _print_report(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
