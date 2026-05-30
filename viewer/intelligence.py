"""SCD Engine — Market Intelligence Layer

Derives human-readable market intelligence from raw P3a snapshot data.
NO scoring. NO writes. Pure observation and classification.

All functions take already-loaded snapshot dicts (or lists of them) and
return structured dicts ready for the cockpit UI to render.

FII broker set (外資主要分點):
  台灣摩根士丹利, 摩根大通, 新加坡商瑞銀, 美商高盛, 美林, 花旗環球
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FII_BROKERS: set[str] = {
    "台灣摩根士丹利",
    "摩根大通",
    "新加坡商瑞銀",
    "美商高盛",
    "美林",
    "花旗環球",
}

# Brokers that are known day-traders / short-term (凱基系列)
DAYTRADER_BROKERS: set[str] = {
    "凱基",
    "凱基-台北",
    "凱基-信義",
    "凱基-敦南",
}


# ---------------------------------------------------------------------------
# Single-stock signal helpers
# ---------------------------------------------------------------------------

def fii_sweep_count(branches: list[dict]) -> int:
    """Number of major FII brokers with net-positive buying today."""
    if not branches:
        return 0
    return sum(
        1 for b in branches
        if b.get("branch") in FII_BROKERS and (b.get("net") or 0) > 0
    )


def fii_sweep_names(branches: list[dict]) -> list[str]:
    """Names of major FII brokers buying today."""
    if not branches:
        return []
    return [
        b["branch"] for b in branches
        if b.get("branch") in FII_BROKERS and (b.get("net") or 0) > 0
    ]


def cost_vs_price(current_price: float | None, main_force_cost: float | None) -> float | None:
    """Return (price - cost) / cost * 100 (%). Positive = above cost."""
    if current_price is None or main_force_cost is None or main_force_cost == 0:
        return None
    return round((current_price - main_force_cost) / main_force_cost * 100, 2)


def safety_label(pct: float | None) -> str:
    """Human label for how close price is to main-force cost."""
    if pct is None:
        return "成本未知 / Cost N/A"
    if pct <= 0:
        return "低於成本 / Below cost"
    if pct <= 2:
        return "緊貼成本 / At cost"
    if pct <= 5:
        return "安全區間 / Safe zone"
    if pct <= 10:
        return "略高成本 / Slightly above"
    return "超出安全區 / Above safe zone"


def is_fii_leading(branches: list[dict]) -> bool:
    """True if top5 is dominated by FII brokers (≥3 major FII net-buying)."""
    return fii_sweep_count(branches) >= 3


def is_daytrader_heavy(branches: list[dict]) -> bool:
    """True if day-trader brokers are prominent in the top5."""
    if not branches:
        return False
    dt_count = sum(
        1 for b in branches
        if b.get("branch") in DAYTRADER_BROKERS and (b.get("net") or 0) > 0
    )
    return dt_count >= 2


def volume_strength(volume: float | None, volume_5d_avg: float | None) -> str | None:
    """Classify volume vs 5-day average."""
    if volume is None or volume_5d_avg is None or volume_5d_avg == 0:
        return None
    ratio = volume / volume_5d_avg
    if ratio >= 3.0:
        return "爆量 / Explosive volume"
    if ratio >= 2.0:
        return "放量 / High volume"
    if ratio >= 1.2:
        return "正常偏多 / Above average"
    if ratio >= 0.8:
        return "正常 / Normal"
    return "量縮 / Shrinking volume"


# ---------------------------------------------------------------------------
# Watchlist categorisation
# ---------------------------------------------------------------------------

_WL_CATEGORIES = [
    "worth_watching",        # 值得觀察
    "strengthening",         # 轉強
    "stable_accumulation",   # 穩定累積
    "false_breakout_risk",   # 潛在假突破
    "high_persistence",      # 高延續性
    "emerging_transition",   # 新轉折
]

_WL_LABELS = {
    "worth_watching":      ("值得觀察", "Worth Watching"),
    "strengthening":       ("轉強股票", "Strengthening"),
    "stable_accumulation": ("穩定累積", "Stable Accumulation"),
    "false_breakout_risk": ("潛在假突破", "False Breakout Risk"),
    "high_persistence":    ("高延續性標的", "High Persistence"),
    "emerging_transition": ("新轉折股票", "Emerging Transition"),
}

_WL_ICONS = {
    "worth_watching":      "👁",
    "strengthening":       "↑",
    "stable_accumulation": "◉",
    "false_breakout_risk": "⚠",
    "high_persistence":    "★",
    "emerging_transition": "⚡",
}


def classify_stock(
    stock: dict,
    streak_data: dict | None = None,   # from ticker_streaks(), keyed by ticker
    all_dates: list[str] | None = None,
    is_new_to_universe: bool = False,
) -> list[str]:
    """Return list of category keys this stock belongs to.

    A stock can belong to multiple categories simultaneously.
    """
    categories: list[str] = []
    price = stock.get("current_price")
    chg = stock.get("change_pct") or 0
    branches = stock.get("top5_branches") or []
    cost = stock.get("main_force_cost")
    mf_buy = stock.get("main_force_buy") or 0
    volume = stock.get("volume") or 0

    sweep = fii_sweep_count(branches)
    above_cost_pct = cost_vs_price(price, cost)

    # --- Worth Watching: FII backing + cost within safe zone ---
    if sweep >= 2 and (above_cost_pct is None or above_cost_pct <= 5):
        categories.append("worth_watching")

    # --- Strengthening: meaningful price gain + institutional backing ---
    if chg >= 5.0 and (sweep >= 2 or (mf_buy > 0 and mf_buy > volume * 0.4)):
        categories.append("strengthening")

    # --- Stable Accumulation: has cost reference + FII buying + moderate move ---
    if cost is not None and sweep >= 2 and abs(chg) <= 8:
        categories.append("stable_accumulation")

    # --- False Breakout Risk: big move but weak/no institutional backing ---
    if chg >= 10.0 and sweep == 0 and not is_daytrader_heavy(branches):
        categories.append("false_breakout_risk")
    # Also flag if day-trader heavy on a big move
    if chg >= 8.0 and is_daytrader_heavy(branches) and not is_fii_leading(branches):
        if "false_breakout_risk" not in categories:
            categories.append("false_breakout_risk")

    # --- High Persistence: long streak in universe ---
    if streak_data and all_dates:
        s = streak_data.get(stock.get("ticker"), {})
        coverage = s.get("coverage_pct", 0)
        cur_streak = s.get("current_streak", 0)
        if coverage >= 70 or cur_streak >= 5:
            categories.append("high_persistence")

    # --- Emerging Transition: new to universe or significant recent entry ---
    if is_new_to_universe:
        categories.append("emerging_transition")
    elif streak_data:
        s = streak_data.get(stock.get("ticker"), {})
        cur_streak = s.get("current_streak", 0)
        first_seen = s.get("first_seen")
        if cur_streak <= 2 and first_seen and all_dates and first_seen in all_dates[-5:]:
            if "emerging_transition" not in categories:
                categories.append("emerging_transition")

    return categories or ["worth_watching"]  # default bucket if nothing matches


def build_stock_signals(
    stock: dict,
    streak_data: dict | None = None,
    prev_snap_stocks: dict | None = None,   # {ticker: stock_dict} for yesterday
) -> dict:
    """Build a rich signal dict for one stock, ready for UI rendering."""
    ticker = stock.get("ticker", "")
    name = stock.get("name", ticker)
    price = stock.get("current_price")
    chg = stock.get("change_pct") or 0
    branches = stock.get("top5_branches") or []
    cost = stock.get("main_force_cost")
    mf_buy = stock.get("main_force_buy") or 0
    volume = stock.get("volume") or 0
    mf_consec = stock.get("main_force_consecutive_days")
    fii_consec = stock.get("fii_consecutive_buy_days")
    sholder_delta = stock.get("shareholder_count_delta_pct")
    margin_ratio = stock.get("margin_maintenance_ratio")
    margin_panic = stock.get("margin_panic_signal", False)
    pa_signals = stock.get("pa_signals_30m") or []
    trend_2h = stock.get("trend_2h")
    checklist = stock.get("checklist") or {}

    sweep = fii_sweep_count(branches)
    sweep_names = fii_sweep_names(branches)
    above_cost_pct = cost_vs_price(price, cost)

    # Build human-readable signal tags
    signals: list[str] = []

    if sweep >= 4:
        signals.append(f"外資聯合掃貨 {sweep} 家 / {sweep} major FII buying")
    elif sweep >= 2:
        signals.append(f"外資 {sweep} 家同步 / {sweep} FII synchronized")

    if mf_consec and mf_consec >= 3:
        signals.append(f"主力連買 {mf_consec} 日 / Main force {mf_consec}-day streak")
    elif mf_consec and mf_consec >= 1:
        signals.append(f"主力今日買進 / Main force buying today")

    if fii_consec and fii_consec >= 3:
        signals.append(f"外資連買 {fii_consec} 日 / FII {fii_consec}-day run")

    if above_cost_pct is not None:
        signals.append(f"距成本 {above_cost_pct:+.1f}% — {safety_label(above_cost_pct)}")
    elif cost is not None:
        signals.append(f"主力成本 {cost:.2f} / MF cost {cost:.2f}")

    if sholder_delta is not None and sholder_delta < -0.5:
        signals.append(f"股東人數下降 {sholder_delta:.1f}% / Shareholders ↓ (bullish)")
    elif sholder_delta is not None and sholder_delta > 1.0:
        signals.append(f"股東人數上升 {sholder_delta:.1f}% / Shareholders ↑ (caution)")

    if margin_panic:
        signals.append("⚠ 融資恐慌訊號 / Margin panic signal")
    elif margin_ratio is not None and margin_ratio <= 145:
        signals.append(f"融資維持率 {margin_ratio:.0f}% — 接近絕望點 / Near despair zone")

    if pa_signals:
        for sig in pa_signals[:2]:
            signals.append(f"PA: {sig}")

    if trend_2h:
        trend_map = {"up": "2H上升趨勢 / 2H uptrend", "down": "2H下降趨勢 / 2H downtrend", "flat": "2H盤整 / 2H flat"}
        signals.append(trend_map.get(trend_2h, f"2H trend: {trend_2h}"))

    if is_daytrader_heavy(branches):
        signals.append("⚠ 日沖主力活躍 / Day-trader branches active")

    # Streak data
    streak_info = {}
    if streak_data:
        s = streak_data.get(ticker, {})
        streak_info = {
            "current_streak": s.get("current_streak", 0),
            "max_streak": s.get("max_streak", 0),
            "coverage_pct": s.get("coverage_pct", 0),
            "appearances": s.get("appearances", 0),
        }

    # Price action context
    if chg >= 20:
        momentum_label = ("漲停 / Limit up", "extreme_up")
    elif chg >= 9:
        momentum_label = ("強勢上漲 / Strong surge", "strong_up")
    elif chg >= 3:
        momentum_label = ("溫和上漲 / Moderate gain", "up")
    elif chg >= -1:
        momentum_label = ("平盤 / Flat", "flat")
    elif chg >= -5:
        momentum_label = ("溫和回落 / Mild pullback", "down")
    else:
        momentum_label = ("明顯下跌 / Sharp decline", "strong_down")

    return {
        "ticker": ticker,
        "name": name,
        "price": price,
        "chg": chg,
        "volume": volume,
        "mf_buy": mf_buy,
        "cost": cost,
        "above_cost_pct": above_cost_pct,
        "fii_sweep": sweep,
        "fii_names": sweep_names,
        "signals": signals,
        "momentum_label": momentum_label[0],
        "momentum_key": momentum_label[1],
        "is_daytrader": is_daytrader_heavy(branches),
        "streak": streak_info,
        "checklist": checklist,
        "margin_ratio": margin_ratio,
        "margin_panic": margin_panic,
        "sholder_delta": sholder_delta,
    }


# ---------------------------------------------------------------------------
# Market-level narrative
# ---------------------------------------------------------------------------

def market_narrative(
    snap: dict,
    streak_data: dict | None = None,
    all_dates: list[str] | None = None,
) -> dict:
    """Derive a market-level narrative from a snapshot.

    Returns:
      {
        tags: [(zh, en, severity), ...],  severity in: positive/warning/neutral/strong
        headline_zh: str,
        headline_en: str,
        breadth_pct: float,
        avg_chg: float,
        fii_sweep_stocks: int,
        universe_size: int,
        advancing: int,
        declining: int,
      }
    """
    stocks = snap.get("stocks", [])
    universe = len(stocks)
    if universe == 0:
        return {"tags": [], "headline_zh": "無數據", "headline_en": "No data",
                "breadth_pct": 0, "avg_chg": 0, "fii_sweep_stocks": 0,
                "universe_size": 0, "advancing": 0, "declining": 0}

    advancing = sum(1 for s in stocks if (s.get("change_pct") or 0) > 0)
    declining = sum(1 for s in stocks if (s.get("change_pct") or 0) < 0)
    flat = universe - advancing - declining
    avg_chg = round(sum((s.get("change_pct") or 0) for s in stocks) / universe, 2)
    breadth_pct = round(100.0 * advancing / universe, 1)

    # FII sweep breadth
    fii_sweep_stocks = sum(
        1 for s in stocks
        if fii_sweep_count(s.get("top5_branches") or []) >= 2
    )
    fii_breadth_pct = round(100.0 * fii_sweep_stocks / universe, 1)

    # Has cost reference
    with_cost = sum(1 for s in stocks if s.get("main_force_cost") is not None)

    # Build narrative tags
    tags: list[tuple[str, str, str]] = []

    # Breadth tag
    if breadth_pct >= 90:
        tags.append(("廣泛上漲", "Broad-based advance", "strong"))
    elif breadth_pct >= 70:
        tags.append(("多數股票上漲", "Majority advancing", "positive"))
    elif breadth_pct >= 50:
        tags.append(("上漲偏多", "Moderate breadth", "neutral"))
    elif breadth_pct >= 30:
        tags.append(("上漲偏少", "Weak breadth", "warning"))
    else:
        tags.append(("市場廣泛回落", "Broad-based decline", "negative"))

    # Magnitude tag
    if avg_chg >= 10:
        tags.append(("市場急速上升", "Rapid market acceleration", "strong"))
    elif avg_chg >= 5:
        tags.append(("整體強勢", "Overall strong momentum", "positive"))
    elif avg_chg >= 2:
        tags.append(("溫和上漲", "Moderate gains", "neutral"))
    elif avg_chg >= -2:
        tags.append(("平盤整理", "Flat consolidation", "neutral"))
    else:
        tags.append(("整體回落", "Market pulling back", "warning"))

    # FII coordination tag
    if fii_sweep_stocks >= universe * 0.4:
        tags.append(("外資大規模掃貨", "Major FII accumulation sweep", "strong"))
    elif fii_sweep_stocks >= universe * 0.2:
        tags.append(("外資積極介入", "Active FII participation", "positive"))
    elif fii_sweep_stocks > 0:
        tags.append(("部分外資跡象", "Selective FII activity", "neutral"))
    else:
        tags.append(("外資訊號不明", "FII signals absent", "neutral"))

    # Cost structure tag
    if with_cost >= universe * 0.4:
        tags.append(("主力成本可見", "Main force cost visible", "positive"))
    elif with_cost > 0:
        tags.append(("部分主力成本可追蹤", "Some cost references tracked", "neutral"))

    # Build headline
    if avg_chg >= 8 and breadth_pct >= 80:
        headline_zh = "市場強勢突破，外資主力齊步拉抬"
        headline_en = "Broad breakout — institutional alignment confirmed"
    elif avg_chg >= 5 and fii_sweep_stocks >= 3:
        headline_zh = "外資積極布局，市場延續上行"
        headline_en = "FII accumulation broadening — uptrend intact"
    elif avg_chg >= 3 and breadth_pct >= 70:
        headline_zh = "多數股票上漲，廣度健康"
        headline_en = "Healthy breadth expansion with moderate gains"
    elif avg_chg >= 0 and breadth_pct >= 50:
        headline_zh = "市場溫和整理，等待訊號"
        headline_en = "Market consolidating — awaiting directional signal"
    elif avg_chg < 0 and breadth_pct < 40:
        headline_zh = "市場回落，注意支撐"
        headline_en = "Market retreating — monitor support levels"
    else:
        headline_zh = "市場狀態中性"
        headline_en = "Market in neutral state"

    return {
        "tags": tags,
        "headline_zh": headline_zh,
        "headline_en": headline_en,
        "breadth_pct": breadth_pct,
        "avg_chg": avg_chg,
        "fii_sweep_stocks": fii_sweep_stocks,
        "fii_breadth_pct": fii_breadth_pct,
        "universe_size": universe,
        "advancing": advancing,
        "declining": declining,
        "flat": flat,
        "with_cost": with_cost,
    }


# ---------------------------------------------------------------------------
# Temporal breadth series (cross-date)
# ---------------------------------------------------------------------------

def temporal_breadth_series(
    snapshots: dict[str, dict],  # {date: snap}
) -> list[dict]:
    """Build a per-date breadth time series for charting.

    Returns list of dicts sorted by date:
      {date, universe, advancing, declining, flat, breadth_pct, avg_chg,
       fii_sweep_stocks, fii_breadth_pct}
    """
    rows = []
    for date in sorted(snapshots.keys()):
        snap = snapshots[date]
        nm = market_narrative(snap)
        rows.append({
            "date": date,
            "universe": nm["universe_size"],
            "advancing": nm["advancing"],
            "declining": nm["declining"],
            "flat": nm["flat"],
            "breadth_pct": nm["breadth_pct"],
            "avg_chg": nm["avg_chg"],
            "fii_sweep_stocks": nm["fii_sweep_stocks"],
            "fii_breadth_pct": nm["fii_breadth_pct"],
        })
    return rows


def ticker_presence_matrix(
    snapshots: dict[str, dict],  # {date: snap}
) -> tuple[list[str], list[str], list[list[float]]]:
    """Build a ticker × date presence + change matrix for heatmap.

    Returns:
      dates: sorted list of dates
      tickers: sorted list of tickers (by total appearances desc)
      matrix: matrix[ticker_idx][date_idx] = change_pct (or None if absent)
    """
    dates = sorted(snapshots.keys())
    all_tickers: set[str] = set()
    for snap in snapshots.values():
        for s in snap.get("stocks", []):
            all_tickers.add(s["ticker"])

    # Sort tickers by appearances (desc)
    ticker_appearances: dict[str, int] = {}
    ticker_names: dict[str, str] = {}
    for date in dates:
        snap = snapshots[date]
        for s in snap.get("stocks", []):
            t = s["ticker"]
            ticker_appearances[t] = ticker_appearances.get(t, 0) + 1
            if not ticker_names.get(t):
                ticker_names[t] = s.get("name", t)

    tickers = sorted(all_tickers, key=lambda t: -ticker_appearances.get(t, 0))
    ticker_labels = [f"{t} {ticker_names.get(t,'')}" for t in tickers]

    # Build matrix
    matrix: list[list[Any]] = []
    for t in tickers:
        row = []
        for date in dates:
            snap = snapshots[date]
            rec = next((s for s in snap.get("stocks", []) if s["ticker"] == t), None)
            if rec is None:
                row.append(None)
            else:
                row.append(rec.get("change_pct") or 0)
        matrix.append(row)

    return dates, ticker_labels, matrix


def streak_chart_data(streak_rows: list[dict]) -> list[dict]:
    """Format streak data for a horizontal bar chart."""
    # Sort by current_streak desc, then max_streak
    sorted_rows = sorted(streak_rows, key=lambda r: (-r.get("current_streak", 0), -r.get("max_streak", 0)))
    return [
        {
            "ticker": r["ticker"],
            "current_streak": r.get("current_streak", 0),
            "max_streak": r.get("max_streak", 0),
            "coverage_pct": r.get("coverage_pct", 0),
            "appearances": r.get("appearances", 0),
        }
        for r in sorted_rows
    ]


# ---------------------------------------------------------------------------
# Watchlist builder (full pass)
# ---------------------------------------------------------------------------

def build_watchlist(
    snap: dict,
    streak_data_list: list[dict] | None = None,  # output of metrics.ticker_streaks()
    all_dates: list[str] | None = None,
    prev_snap: dict | None = None,
) -> dict[str, list[dict]]:
    """Return {category_key: [signal_dict, ...]} for the watchlist panels.

    Stocks can appear in multiple categories.
    """
    stocks = snap.get("stocks", [])
    if not stocks:
        return {cat: [] for cat in _WL_CATEGORIES}

    # Index streak data by ticker
    streak_by_ticker: dict[str, dict] = {}
    if streak_data_list:
        for row in streak_data_list:
            streak_by_ticker[row["ticker"]] = row

    # Determine which tickers are new to universe vs previous snapshot
    prev_tickers: set[str] = set()
    if prev_snap:
        prev_tickers = {s["ticker"] for s in prev_snap.get("stocks", [])}
    current_tickers = {s["ticker"] for s in stocks}
    new_tickers = current_tickers - prev_tickers

    # Index previous snapshot stocks for comparison
    prev_stocks: dict[str, dict] = {}
    if prev_snap:
        for s in prev_snap.get("stocks", []):
            prev_stocks[s["ticker"]] = s

    result: dict[str, list[dict]] = {cat: [] for cat in _WL_CATEGORIES}

    for stock in stocks:
        ticker = stock.get("ticker", "")
        is_new = ticker in new_tickers
        cats = classify_stock(stock, streak_by_ticker, all_dates, is_new_to_universe=is_new)
        sig = build_stock_signals(stock, streak_by_ticker, prev_stocks)
        for cat in cats:
            if cat in result:
                result[cat].append(sig)

    # Sort each category by FII sweep desc, then chg desc
    for cat in result:
        result[cat].sort(key=lambda s: (-s["fii_sweep"], -(s["chg"] or 0)))

    return result


# ---------------------------------------------------------------------------
# Exported label maps (for UI)
# ---------------------------------------------------------------------------

WATCHLIST_LABELS = _WL_LABELS
WATCHLIST_ICONS = _WL_ICONS
