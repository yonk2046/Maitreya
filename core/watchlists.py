"""SCD Engine — Permanent Watchlist Definitions  (P3c)

Tier A tickers are market regime anchors. They are always fetched —
branch data, cost, FII flow — regardless of cross-signal status.

Design principle: many mid-cap movements are spillover from
large-cap rotation. Tracking the anchors tells you WHY the
small caps are moving before price confirms it.
"""
from __future__ import annotations
from typing import Any

# ---------------------------------------------------------------------------
# Tier A — Regime Anchors  永久追蹤
# ---------------------------------------------------------------------------

TIER_A: dict[str, dict[str, Any]] = {
    # ── Semiconductors 半導體 ──────────────────────────────────────────────
    "2330": {"name": "台積電",  "name_en": "TSMC",       "group": "semiconductor", "group_zh": "半導體"},
    "2454": {"name": "聯發科",  "name_en": "MediaTek",   "group": "semiconductor", "group_zh": "半導體"},
    # ── Electronics / EMS 電子代工 ────────────────────────────────────────
    "2317": {"name": "鴻海",    "name_en": "Hon Hai",    "group": "electronics",   "group_zh": "電子代工"},
    "2382": {"name": "廣達",    "name_en": "Quanta",     "group": "electronics",   "group_zh": "電子代工"},
    "2308": {"name": "台達電",  "name_en": "Delta",      "group": "electronics",   "group_zh": "電子代工"},
    # ── Financials 金融權值 ───────────────────────────────────────────────
    "2881": {"name": "富邦金",  "name_en": "Fubon FHC",  "group": "financials",    "group_zh": "金融"},
    "2882": {"name": "國泰金",  "name_en": "Cathay FHC", "group": "financials",    "group_zh": "金融"},
    "2891": {"name": "中信金",  "name_en": "CTBC FHC",   "group": "financials",    "group_zh": "金融"},
}

TIER_A_CODES: frozenset[str] = frozenset(TIER_A.keys())

# ---------------------------------------------------------------------------
# Radar — daily cockpit watch panel  (5 tech leaders only)
# Financial stocks removed: use market_flow / regime panels for FHC tracking.
# ---------------------------------------------------------------------------

RADAR_TICKERS: list[str] = ["2330", "2317", "2454", "2308", "2382"]
# 台積電, 鴻海, 聯發科, 台達電, 廣達

# ---------------------------------------------------------------------------
# Sector taxonomy  (for leadership rotation)
# ---------------------------------------------------------------------------

SECTOR_GROUPS: dict[str, dict[str, Any]] = {
    "semiconductor": {
        "zh": "半導體", "en": "Semiconductors",
        "tickers": ["2330", "2454", "2303", "2344", "2408", "2337", "6770", "3711", "2449"],
    },
    "electronics": {
        "zh": "電子代工", "en": "Electronics / EMS",
        "tickers": ["2317", "2382", "2308", "2354", "2356", "2324", "2353", "2312"],
    },
    "financials": {
        "zh": "金融", "en": "Financials",
        "tickers": ["2881", "2882", "2891", "2883", "2884", "2885", "2886", "2887", "2892"],
    },
    "shipping": {
        "zh": "航運", "en": "Shipping",
        "tickers": ["2609", "2610", "2603", "2615", "5880"],
    },
    "memory": {
        "zh": "記憶體", "en": "Memory",
        "tickers": ["2344", "2408", "3260", "4863", "6770", "2337"],
    },
    "ai_infra": {
        "zh": "AI基礎設施", "en": "AI Infrastructure",
        "tickers": ["2330", "2454", "3711", "6669", "2379", "2382"],
    },
    "materials": {
        "zh": "材料/化工", "en": "Materials / Chemicals",
        "tickers": ["1301", "1303", "1326", "2002", "1802"],
    },
    "other": {
        "zh": "其他", "en": "Other",
        "tickers": [],
    },
}

# Lookup: ticker → primary sector group
_TICKER_TO_GROUP: dict[str, str] = {}
for _grp, _meta in SECTOR_GROUPS.items():
    for _t in _meta["tickers"]:
        if _t not in _TICKER_TO_GROUP:  # first assignment wins (most specific)
            _TICKER_TO_GROUP[_t] = _grp


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def tier_a_tickers() -> list[str]:
    """Sorted list of Tier A ticker codes."""
    return sorted(TIER_A.keys())


def stock_group(ticker: str) -> str:
    """Return the primary sector group for a ticker. Falls back to 'other'."""
    if ticker in TIER_A:
        return TIER_A[ticker]["group"]
    return _TICKER_TO_GROUP.get(ticker, "other")


def group_meta(group: str) -> dict[str, Any]:
    return SECTOR_GROUPS.get(group, {"zh": group, "en": group, "tickers": []})


def all_watched_tickers() -> frozenset[str]:
    """Union of Tier A + all sector taxonomy tickers."""
    tickers: set[str] = set(TIER_A.keys())
    for meta in SECTOR_GROUPS.values():
        tickers.update(meta["tickers"])
    return frozenset(tickers)


# Name corrections for tickers whose names arrive garbled from the data source
# (Big5 / CP950 encoding mismatch causes U+FFFD replacement characters)
NAME_CORRECTIONS: dict[str, str] = {
    "2353": "宏碁",    # 碁 (U+7881) garbles in some source encodings
    "2049": "上銀",
    "3673": "TPK-KY",
}


def build_name_map(snapshots: list[dict[str, Any]]) -> dict[str, str]:
    """Build a {ticker: name} mapping from loaded snapshot records.

    Walks every stock record across all snapshots (most-recent wins),
    then merges in TIER_A canonical names so anchors always have correct names.
    Returns an empty dict if snapshots is empty.

    Usage (cockpit or any consumer with pre-loaded snaps):
        name_map = build_name_map(snaps)
        display = f"{ticker} {name_map.get(ticker, ticker)}"
    """
    out: dict[str, str] = {}
    for snap in snapshots:
        for s in snap.get("stocks", []):
            t = s.get("ticker")
            n = s.get("name") or ""
            if t and n and n != t:
                out[t] = n
    # Tier A always overrides with canonical names
    for t, meta in TIER_A.items():
        out[t] = meta["name"]
    # Apply encoding corrections (overrides garbled names from data source)
    for t, corrected in NAME_CORRECTIONS.items():
        if t not in TIER_A:  # don't override TIER_A entries
            out[t] = corrected
    return out


def ticker_display(ticker: str, name_map: dict[str, str] | None = None) -> str:
    """Return "TICKER 公司名" string.  Falls back to TIER_A, then ticker only."""
    if name_map:
        name = name_map.get(ticker, "")
    else:
        name = TIER_A.get(ticker, {}).get("name", "")
    return f"{ticker} {name}" if name and name != ticker else ticker
