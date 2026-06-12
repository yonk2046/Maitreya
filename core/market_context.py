"""SCD Engine — Market Context & Temporal Intelligence  (P3c)

Five pure-observation analyses that span multiple snapshots:

  1. accumulation_velocity    — how fast is capital building in a stock?
  2. sponsorship_persistence  — are the same brokers repeatedly buying?
  3. regime_shift             — is the market changing character?
  4. failed_breakout_memory   — recent fake-breakout / distribution patterns?
  5. leadership_rotation      — which sector is leading capital flows?

P3a constraint: all scoring abstained. These functions produce
qualitative labels and quantitative signals from raw ingest data only.
No writes. No caching. Pure functions.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.watchlists import SECTOR_GROUPS, stock_group


# ===========================================================================
# 1.  Accumulation Velocity  累積速度
# ===========================================================================

def accumulation_velocity(
    ticker: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Measure speed and consistency of capital accumulation.

    records: sorted oldest→newest, each having at minimum:
      { date, main_force_buy (int|None), volume (int|None), change_pct (float|None) }

    Returns
    -------
    ticker, total_days, days_with_data,
    net_cumulative     — sum of main_force_buy across all days
    velocity_3d        — average daily change in mf_buy over last 3 real obs
    acceleration       — is velocity itself speeding up? (second diff)
    buy_days           — days with positive main_force_buy
    sell_days          — days with negative main_force_buy
    streak             — consecutive buy-days at the TAIL
    label_zh / label_en
    """
    if not records:
        return _empty_velocity(ticker)

    buy_vals = [r.get("main_force_buy") for r in records]
    real_buys = [v for v in buy_vals if v is not None]
    buy_days  = sum(1 for v in real_buys if v > 0)
    sell_days = sum(1 for v in real_buys if v < 0)

    # Streak — consecutive positive tail
    streak = 0
    for r in reversed(records):
        v = r.get("main_force_buy")
        if v is not None and v > 0:
            streak += 1
        elif v is not None:
            break

    net_cumulative = sum(real_buys)

    # 3-day velocity
    velocity_3d: float | None = None
    if len(real_buys) >= 2:
        window = real_buys[-3:]
        diffs = [window[i + 1] - window[i] for i in range(len(window) - 1)]
        velocity_3d = sum(diffs) / len(diffs) if diffs else None

    # Acceleration (second diff)
    accel: float | None = None
    if len(real_buys) >= 3:
        w = real_buys[-4:]
        if len(w) >= 3:
            diffs = [w[i + 1] - w[i] for i in range(len(w) - 1)]
            if len(diffs) >= 2:
                second = [diffs[i + 1] - diffs[i] for i in range(len(diffs) - 1)]
                accel = sum(second) / len(second)

    # Label
    if streak >= 3 and (velocity_3d or 0) > 0:
        label_zh, label_en = "加速吸籌", "Accelerating Accumulation"
    elif streak >= 3:
        label_zh, label_en = "持續吸籌", "Sustained Accumulation"
    elif streak == 2:
        label_zh, label_en = "連續兩日", "2-Day Streak"
    elif streak == 1:
        label_zh, label_en = "初現買盤", "Emerging Buy"
    elif buy_days == 0:
        label_zh, label_en = "無主力跡象", "No Capital Flow"
    else:
        label_zh, label_en = "間歇吸籌", "Intermittent Accumulation"

    return {
        "ticker":        ticker,
        "total_days":    len(records),
        "days_with_data": len(real_buys),
        "net_cumulative": int(net_cumulative),
        "velocity_3d":   round(velocity_3d) if velocity_3d is not None else None,
        "acceleration":  round(accel)        if accel       is not None else None,
        "buy_days":      buy_days,
        "sell_days":     sell_days,
        "streak":        streak,
        "label_zh":      label_zh,
        "label_en":      label_en,
    }


def _empty_velocity(ticker: str) -> dict[str, Any]:
    return dict(
        ticker=ticker, total_days=0, days_with_data=0,
        net_cumulative=0, velocity_3d=None, acceleration=None,
        buy_days=0, sell_days=0, streak=0,
        label_zh="無資料", label_en="No Data",
    )


# ===========================================================================
# 2.  Sponsorship Persistence  贊助持續性
# ===========================================================================

def sponsorship_persistence(
    ticker: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Track whether the same brokers keep appearing in the top branches.

    High persistence → institutional commitment, not one-off momentum.
    Low persistence  → retail chasing or unstable interest.

    records: each may have top5_branches: [{branch|broker, net|netBuy, ...}]
    """
    if not records:
        return _empty_sponsorship(ticker)

    appearances: dict[str, int] = {}
    days_with_branches = 0

    for r in records:
        branches = r.get("top5_branches") or []
        if not branches:
            continue
        days_with_branches += 1
        seen_today: set[str] = set()
        for b in branches:
            name = b.get("branch") or b.get("broker") or ""
            net  = b.get("net") or b.get("netBuy") or 0
            if name and net > 0 and name not in seen_today:
                appearances[name] = appearances.get(name, 0) + 1
                seen_today.add(name)

    if not appearances:
        return _empty_sponsorship(ticker)

    persistent = {k: v for k, v in appearances.items() if v >= 2}
    top_broker = max(appearances, key=appearances.__getitem__)
    top_days   = appearances[top_broker]
    score      = top_days / max(days_with_branches, 1)

    if score >= 0.7:
        label_zh, label_en = "高持續贊助", "Strong Sponsor Persistence"
    elif score >= 0.4:
        label_zh, label_en = "中度持續", "Moderate Persistence"
    else:
        label_zh, label_en = "分散/不穩", "Scattered / Unstable"

    return {
        "ticker":               ticker,
        "days_with_branches":   days_with_branches,
        "broker_appearances":   appearances,
        "persistent_brokers":   persistent,
        "top_persistent_broker": top_broker,
        "top_broker_days":      top_days,
        "persistence_score":    round(score, 3),
        "label_zh":             label_zh,
        "label_en":             label_en,
    }


def _empty_sponsorship(ticker: str) -> dict[str, Any]:
    return dict(
        ticker=ticker, days_with_branches=0, broker_appearances={},
        persistent_brokers={}, top_persistent_broker=None,
        top_broker_days=0, persistence_score=0.0,
        label_zh="無分點資料", label_en="No Branch Data",
    )


# ===========================================================================
# 3.  Regime Shift Detection  市場體制轉換
# ===========================================================================

def regime_shift(
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Observe market-wide character changes across dates.

    Per-snapshot metrics:
      breadth      — fraction of universe with positive main_force_buy
      avg_chg      — mean change_pct across universe
      fii_active   — fraction of stocks with non-zero fii_net_buy
      vol_index    — total volume normalized to first available day

    Returns regime label, trend, and transition detection.
    """
    if not snapshots:
        return _empty_regime()

    dates, breadth_s, avg_chg_s, fii_s, vol_s = [], [], [], [], []
    base_vol: float | None = None

    for snap in snapshots:
        stocks = snap.get("stocks", [])
        if not stocks:
            continue
        dates.append(snap.get("date", "?"))

        mf_vals  = [s.get("main_force_buy") for s in stocks if s.get("main_force_buy") is not None]
        chg_vals = [s.get("change_pct")     for s in stocks if s.get("change_pct")     is not None]
        fii_vals = [s.get("fii_net_buy")    for s in stocks if s.get("fii_net_buy")    is not None]
        vol_vals = [s.get("volume")         for s in stocks if s.get("volume")         is not None]

        breadth   = sum(1 for v in mf_vals if v > 0) / max(len(mf_vals), 1)
        avg_chg   = sum(chg_vals) / len(chg_vals) if chg_vals else 0.0
        fii_act   = sum(1 for v in fii_vals if v != 0) / max(len(fii_vals), 1) if fii_vals else 0.0
        total_vol = sum(vol_vals)

        if base_vol is None:
            base_vol = total_vol if total_vol > 0 else 1
        vol_idx = total_vol / base_vol

        breadth_s.append(round(breadth, 3))
        avg_chg_s.append(round(avg_chg, 3))
        fii_s.append(round(fii_act, 3))
        vol_s.append(round(vol_idx, 3))

    if not dates:
        return _empty_regime()

    latest_b   = breadth_s[-1]
    latest_chg = avg_chg_s[-1]

    # Breadth trend over last 3 points
    breadth_trend = "flat"
    if len(breadth_s) >= 2:
        delta = breadth_s[-1] - breadth_s[-2]
        if len(breadth_s) >= 3:
            delta2 = breadth_s[-2] - breadth_s[-3]
            if delta > 0.1 and delta2 >= 0:
                breadth_trend = "rising_fast"
            elif delta > 0.02:
                breadth_trend = "rising"
            elif delta < -0.1:
                breadth_trend = "falling_fast"
            elif delta < -0.02:
                breadth_trend = "falling"
        else:
            breadth_trend = "rising" if delta > 0.02 else ("falling" if delta < -0.02 else "flat")

    # Regime classification
    if latest_b >= 0.75 and latest_chg > 3.0:
        regime_zh, regime_en, regime_color = "強勢進攻", "Risk-On / Offensive",  "#52B788"
    elif latest_b >= 0.6 and latest_chg > 1.0:
        regime_zh, regime_en, regime_color = "溫和偏多", "Mild Risk-On",          "#7EB8D4"
    elif latest_b < 0.25 and latest_chg < -2.0:
        regime_zh, regime_en, regime_color = "全面撤退", "Risk-Off / Retreat",    "#E05C7A"
    elif latest_b < 0.35:
        regime_zh, regime_en, regime_color = "資金觀望", "Capital Waiting",        "#D4A84B"
    elif latest_chg < 0:
        regime_zh, regime_en, regime_color = "偏弱整理", "Mild Risk-Off",          "#C47A5A"
    else:
        regime_zh, regime_en, regime_color = "中性整理", "Neutral / Consolidating","#6B8EAA"

    # Transition detection
    transition_detected, transition_note = False, ""
    if len(breadth_s) >= 2:
        b_delta = breadth_s[-1] - breadth_s[-2]
        c_delta = avg_chg_s[-1] - avg_chg_s[-2]
        if abs(b_delta) >= 0.25 or abs(c_delta) >= 3.0:
            transition_detected = True
            if b_delta > 0:
                transition_note = "市場突然轉強 — 可能 Risk-Off→Risk-On 切換"
            else:
                transition_note = "市場突然轉弱 — 資金快速撤出訊號"

    return {
        "dates":               dates,
        "breadth_series":      breadth_s,
        "avg_chg_series":      avg_chg_s,
        "fii_active_series":   fii_s,
        "vol_series":          vol_s,
        "breadth_trend":       breadth_trend,
        "latest_breadth":      latest_b,
        "latest_avg_chg":      latest_chg,
        "latest_vol_index":    vol_s[-1] if vol_s else 1.0,
        "regime_label_zh":     regime_zh,
        "regime_label_en":     regime_en,
        "regime_color":        regime_color,
        "transition_detected": transition_detected,
        "transition_note":     transition_note,
    }


def _empty_regime() -> dict[str, Any]:
    return dict(
        dates=[], breadth_series=[], avg_chg_series=[],
        fii_active_series=[], vol_series=[], breadth_trend="flat",
        latest_breadth=0.0, latest_avg_chg=0.0, latest_vol_index=1.0,
        regime_label_zh="無資料", regime_label_en="No Data",
        regime_color="#6B8EAA", transition_detected=False, transition_note="",
    )


# ===========================================================================
# 4.  Failed Breakout Memory  假突破記憶
# ===========================================================================

def failed_breakout_memory(
    ticker: str,
    records: list[dict[str, Any]],
    lookback: int = 10,
) -> dict[str, Any]:
    """
    Detect if a stock had an apparent breakout (volume spike + price up)
    followed by weakness (price down + main_force retreating).

    Breakout: volume > 1.8× recent avg AND change_pct > 2%
    Retreat: ≥2 of next 3 days have (change_pct < 0 OR main_force_buy < 0)
    """
    recent = records[-lookback:] if len(records) > lookback else records
    if len(recent) < 3:
        return _empty_breakout(ticker)

    vols = [r.get("volume") or 0 for r in recent]
    # Volume baseline: exclude last 2 days
    baseline_vols = vols[:-2] if len(vols) > 2 else vols
    avg_vol = sum(baseline_vols) / max(len(baseline_vols), 1)

    found: dict[str, Any] = {}
    for i in range(len(recent) - 2):
        day = recent[i]
        vol = day.get("volume") or 0
        chg = day.get("change_pct") or 0

        if vol > avg_vol * 1.8 and chg > 2.0:
            retreat = 0
            for j in range(i + 1, min(i + 4, len(recent))):
                nx = recent[j]
                if (nx.get("change_pct") or 0) < 0 or (nx.get("main_force_buy") or 0) < 0:
                    retreat += 1
            if retreat >= 2:
                found = {
                    "date":         day.get("date"),
                    "breakout_chg": chg,
                    "vol_ratio":    round(vol / max(avg_vol, 1), 2),
                    "retreat_days": retreat,
                }
                # keep the most recent match (last wins)

    if found:
        risk = "⚠ 高風險假突破" if found["retreat_days"] >= 3 else "⚡ 疑似假突破"
        risk_en = "High-Risk Failed Breakout" if found["retreat_days"] >= 3 else "Possible Failed Breakout"
        return {
            "ticker":                    ticker,
            "failed_breakout_detected":  True,
            "breakout_date":             found["date"],
            "breakout_chg":              found["breakout_chg"],
            "vol_ratio":                 found["vol_ratio"],
            "retreat_days":              found["retreat_days"],
            "label_zh":                  risk,
            "label_en":                  risk_en,
        }

    return {
        "ticker":                   ticker,
        "failed_breakout_detected": False,
        "breakout_date":            None,
        "breakout_chg":             None,
        "vol_ratio":                None,
        "retreat_days":             0,
        "label_zh":                 "無假突破跡象",
        "label_en":                 "No Failed Breakout Signal",
    }


def _empty_breakout(ticker: str) -> dict[str, Any]:
    return dict(
        ticker=ticker, failed_breakout_detected=False,
        breakout_date=None, breakout_chg=None, vol_ratio=None,
        retreat_days=0, label_zh="資料不足", label_en="Insufficient Data",
    )


# ===========================================================================
# 5.  Leadership Rotation  資金輪動偵測
# ===========================================================================

def leadership_rotation(
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Determine which sector is leading capital flows across dates.

    For each snapshot, sum main_force_buy by sector group.
    Compare latest vs prior to detect rotation.
    """
    if not snapshots:
        return _empty_leadership()

    per_snap: list[dict[str, dict[str, Any]]] = []
    snap_dates: list[str] = []

    for snap in snapshots:
        date   = snap.get("date", "?")
        stocks = snap.get("stocks", [])
        flows: dict[str, dict[str, Any]] = {}
        for s in stocks:
            ticker = s.get("ticker", "")
            mfb    = s.get("main_force_buy") or 0
            group  = stock_group(ticker)
            if group not in flows:
                flows[group] = {"total_buy": 0, "ticker_count": 0, "tickers": []}
            flows[group]["total_buy"]     += mfb
            flows[group]["ticker_count"]  += 1
            flows[group]["tickers"].append(ticker)
        per_snap.append(flows)
        snap_dates.append(date)

    latest_flows = per_snap[-1] if per_snap else {}
    prior_flows  = per_snap[-2] if len(per_snap) >= 2 else {}

    ranked       = sorted(latest_flows.items(), key=lambda kv: kv[1]["total_buy"], reverse=True)
    leading      = ranked[0][0] if ranked else None

    prior_ranked = sorted(prior_flows.items(), key=lambda kv: kv[1]["total_buy"], reverse=True) if prior_flows else []
    prior_lead   = prior_ranked[0][0] if prior_ranked else None

    rotation     = (leading != prior_lead and prior_lead is not None)

    # Enrich with labels
    flows_out: dict[str, Any] = {}
    for sector, data in latest_flows.items():
        meta = SECTOR_GROUPS.get(sector, {})
        flows_out[sector] = {
            **data,
            "label_zh": meta.get("zh", sector),
            "label_en": meta.get("en", sector),
            "avg_buy":  round(data["total_buy"] / max(data["ticker_count"], 1)),
        }

    lead_meta = SECTOR_GROUPS.get(leading, {}) if leading else {}

    return {
        "snap_dates":        snap_dates,
        "sector_flows":      flows_out,
        "leading_sector":    leading,
        "leading_label_zh":  lead_meta.get("zh", leading or "?"),
        "leading_label_en":  lead_meta.get("en", leading or "?"),
        "prior_leading":     prior_lead,
        "rotation_detected": rotation,
        "rotation_from":     prior_lead,
        "rotation_to":       leading if rotation else None,
        "ranked_sectors":    [s[0] for s in ranked],
    }


def _empty_leadership() -> dict[str, Any]:
    return dict(
        snap_dates=[], sector_flows={},
        leading_sector=None, leading_label_zh="無資料", leading_label_en="No Data",
        prior_leading=None, rotation_detected=False,
        rotation_from=None, rotation_to=None, ranked_sectors=[],
    )


# ===========================================================================
# Batch helper: full context for one ticker across snapshots
# ===========================================================================

def full_ticker_context(
    ticker: str,
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run accumulation + sponsorship + failed-breakout for one ticker."""
    records: list[dict[str, Any]] = []
    for snap in snapshots:
        rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
        records.append({
            "date":          snap.get("date", "?"),
            "main_force_buy": rec.get("main_force_buy")  if rec else None,
            "volume":         rec.get("volume")           if rec else None,
            "change_pct":     rec.get("change_pct")       if rec else None,
            "current_price":  rec.get("current_price")    if rec else None,
            "top5_branches":  rec.get("top5_branches")    if rec else [],
            "present":        rec is not None,
        })
    return {
        "ticker":        ticker,
        "accumulation":  accumulation_velocity(ticker, records),
        "sponsorship":   sponsorship_persistence(ticker, records),
        "failed_breakout": failed_breakout_memory(ticker, records),
    }


# ===========================================================================
# 6.  Weakening / Distribution Detection  轉弱出貨偵測
# ===========================================================================
# Deterministic observation-layer detector (same pattern as failed_breakout).
# Does NOT touch composite_score / tier / gates — AI_GOVERNANCE compliant.

_W2_FII_RATIO      = 0.30   # FII sell must be ≥30% of main-force buy to flag
_W5_SELL_RATIO     = 1.00   # branch totalSellVol > totalBuyVol
_W5_CHURN_RATIO    = 0.60   # top-3 buy branches selling ≥60% of what they buy


def weakening_profile(
    ticker: str,
    snapshots: list[dict[str, Any]],
    branch_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect distribution / weakening behaviour for one ticker.

    Five deterministic flags:
      W1 momentum_decay   — buy streak ≥3 but velocity_3d < 0 and F(n) < F(n-1)
      W2 engine_divergence— main force buying while FII net-selling (≥30%)
      W3 vanished         — had streak ≥3 in window, absent from latest snapshot
      W4 retail_takeover  — broker_count_diff > 0 OR price-down-margin-up ≥3d/10d
      W5 branch_pressure  — sellVol > buyVol at branch level, or top buyers churning

    Severity: red (W3 or ≥3 flags) > orange (2) > yellow (1) > none (0).
    """
    if not snapshots:
        return _empty_weakening(ticker)

    records: list[dict[str, Any]] = []
    for snap in snapshots:
        rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
        records.append({
            "date":           snap.get("date", "?"),
            "main_force_buy": rec.get("main_force_buy") if rec else None,
            "present":        rec is not None,
            "stock":          rec,
        })

    latest       = records[-1]
    latest_stock = latest["stock"] or {}

    # Recency gate: how many snapshots since last seen
    snaps_since_seen = 0
    for r in reversed(records):
        if r["present"]:
            break
        snaps_since_seen += 1
    if snaps_since_seen > 3:
        # vanished long ago — stale, not an active weakening signal
        return _empty_weakening(ticker)

    acc          = accumulation_velocity(
        ticker,
        [{"date": r["date"], "main_force_buy": r["main_force_buy"],
          "volume": None, "change_pct": None} for r in records],
    )

    real_buys = [r["main_force_buy"] for r in records if r["main_force_buy"] is not None]

    # max historical streak inside window (for W3)
    max_streak = 0
    cur = 0
    for r in records:
        v = r["main_force_buy"]
        if v is not None and v > 0:
            cur += 1
            max_streak = max(max_streak, cur)
        elif v is not None:
            cur = 0

    flags: list[dict[str, str]] = []

    # W1 momentum decay
    if (acc["streak"] >= 3 and (acc.get("velocity_3d") or 0) < 0
            and len(real_buys) >= 2 and real_buys[-1] < real_buys[-2]):
        flags.append({"code": "W1", "zh": "動能衰竭",
                      "detail": f"連買{acc['streak']}日但速度 {round(acc['velocity_3d']):+,}/日"})

    # W2 dual-engine divergence
    mfb = latest_stock.get("main_force_buy") or 0
    fii = latest_stock.get("fii_net_buy")
    if mfb > 0 and fii is not None and fii < 0 and abs(fii) >= _W2_FII_RATIO * mfb:
        flags.append({"code": "W2", "zh": "雙引擎分歧",
                      "detail": f"主力 +{mfb:,} vs 外資 {fii:,}"})

    # W3 vanished after accumulation
    if max_streak >= 3 and not latest["present"]:
        last_seen = next((r["date"] for r in reversed(records) if r["present"]), "?")
        flags.append({"code": "W3", "zh": "主力消失",
                      "detail": f"曾連買{max_streak}日，缺席{snaps_since_seen}日（最後 {last_seen[5:]}）"})

    # W4 retail takeover
    bcd = latest_stock.get("broker_count_diff")
    pdmu = latest_stock.get("price_down_margin_up_days_10d") or 0
    if (bcd is not None and bcd > 0) or pdmu >= 3:
        parts = []
        if bcd is not None and bcd > 0:
            parts.append(f"家數差 +{bcd}")
        if pdmu >= 3:
            parts.append(f"價跌融資增 {pdmu}日/10日")
        flags.append({"code": "W4", "zh": "散戶接盤", "detail": "、".join(parts)})

    # W5 branch-level sell pressure
    if branch_data:
        tb = branch_data.get("totalBuyVol") or 0
        ts = branch_data.get("totalSellVol") or 0
        churn_flag = False
        bb = branch_data.get("buyBranches") or []
        top3 = bb[:3]
        if top3:
            t3b = sum(b.get("buyVol") or 0 for b in top3)
            t3s = sum(b.get("sellVol") or 0 for b in top3)
            churn_flag = t3b > 0 and (t3s / t3b) >= _W5_CHURN_RATIO
        if (tb > 0 and ts > _W5_SELL_RATIO * tb) or churn_flag:
            detail = f"分點賣 {ts:,} vs 買 {tb:,}"
            if churn_flag:
                detail += "、前三買點邊買邊倒"
            flags.append({"code": "W5", "zh": "分點賣壓", "detail": detail})

    n = len(flags)
    has_w3 = any(f["code"] == "W3" for f in flags)
    if (has_w3 and n >= 2) or n >= 3:
        severity, label_zh, label_en = "red", "出貨確認", "Distribution Confirmed"
    elif n == 2 or (has_w3 and n == 1):
        severity, label_zh, label_en = "orange", "轉弱", "Weakening"
    elif n == 1:
        severity, label_zh, label_en = "yellow", "失速", "Stalling"
    else:
        severity, label_zh, label_en = "none", "—", "—"

    return {
        "ticker": ticker,
        "flags": flags,
        "flag_count": n,
        "severity": severity,
        "label_zh": label_zh,
        "label_en": label_en,
        "streak": acc["streak"],
        "max_streak": max_streak,
        "velocity_3d": acc.get("velocity_3d"),
        "net_cumulative": acc.get("net_cumulative") or 0,
        "present_latest": latest["present"],
        "snaps_since_seen": snaps_since_seen,
    }


def _empty_weakening(ticker: str) -> dict[str, Any]:
    return dict(ticker=ticker, flags=[], flag_count=0, severity="none",
                label_zh="—", label_en="—", streak=0, max_streak=0,
                velocity_3d=None, net_cumulative=0, present_latest=False)


# ---------------------------------------------------------------------------
# P0.6 — Dual-anchor main-force cost (雙錨主力成本)
# ---------------------------------------------------------------------------
# Problem (handoff 20260612, case study 4938 和碩): the short-window cost
# (upstream avg_buy_cost ≈ last 5 sessions) systematically OVERESTIMATES the
# real holder base during a sustained rally — price/cost looks safe while the
# episode's actual sell-pressure source sits far lower.
#
# Two anchors:
#   cost_recent           — latest snapshot's main_force_cost (newest batch)
#   cost_episode_weighted — Σ(cost_i × mfb_i) / Σ(mfb_i) over the current
#                           buy episode (consecutive trailing records with
#                           mfb > 0) = volume-weighted real entry base
#
# Divergence (recent vs episode) > threshold → 「⚠ 成本背離」latecomer-chasing
# signal. Entry-gate consumers should use cost_conservative = min(両錨).
# Display/intelligence layer only in P3a — schema entry deferred to P3b.

_COST_DIVERGENCE_PCT_DEFAULT = 5.0   # config: gates.cost_safety.divergence_alert_pct


def dual_cost_anchor(
    ticker: str,
    snapshots: list[dict[str, Any]],
    divergence_alert_pct: float = _COST_DIVERGENCE_PCT_DEFAULT,
) -> dict[str, Any]:
    """Compute the dual cost anchors for one ticker. Pure function.

    Episode = trailing consecutive records (by snapshot, skipping absent
    days breaks the chain) where main_force_buy > 0. Records lacking a
    usable cost are kept in the episode but excluded from the weighting.
    """
    # Collect (cost, mfb) chronologically for this ticker
    daily: list[tuple[float | None, float | None]] = []
    for snap in snapshots:
        rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
        if rec is None:
            daily.append((None, None))   # absent marker
        else:
            daily.append((rec.get("main_force_cost"), rec.get("main_force_buy")))

    # Latest present record → recent anchor
    cost_recent: float | None = None
    for cost, _mfb in reversed(daily):
        if cost is not None:
            cost_recent = float(cost)
            break

    # Walk the trailing buy episode (mfb > 0, absence breaks)
    w_sum = 0.0
    cw_sum = 0.0
    episode_len = 0
    for cost, mfb in reversed(daily):
        if mfb is None or mfb <= 0:
            break
        episode_len += 1
        if cost is not None and cost > 0:
            w_sum += mfb
            cw_sum += float(cost) * mfb

    cost_episode: float | None = (cw_sum / w_sum) if w_sum > 0 else None

    divergence_pct: float | None = None
    diverged = False
    if cost_recent is not None and cost_episode and cost_episode > 0:
        divergence_pct = (cost_recent - cost_episode) / cost_episode * 100.0
        diverged = abs(divergence_pct) > divergence_alert_pct

    candidates = [c for c in (cost_recent, cost_episode) if c is not None]
    cost_conservative = min(candidates) if candidates else None

    return {
        "ticker": ticker,
        "cost_recent": cost_recent,
        "cost_episode_weighted": round(cost_episode, 2) if cost_episode else None,
        "cost_conservative": round(cost_conservative, 2) if cost_conservative else None,
        "episode_len": episode_len,
        "divergence_pct": round(divergence_pct, 2) if divergence_pct is not None else None,
        "diverged": diverged,
    }
