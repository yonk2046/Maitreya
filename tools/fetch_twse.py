"""Fetch TWSE OpenAPI data: MI_INDEX20 (volume top 20) + MI_MARGN (margin balance).

Both endpoints are CORS-enabled JSON, no auth required.
"""

import json
import sys
from _common import http_get_json, parse_int_safe, parse_float_safe, log

MI_INDEX20_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX20"
MI_MARGN_URL   = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
# Full-market daily OHLC — used to capture next-day OPEN price for the
# paper-trading backtest settlement (spec §1: 次日開盤價結算).
STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"


# A4 (2026-09-22): session-dated full-market quotes. STOCK_DAY_ALL (OpenAPI) only
# serves "the latest day" and still shows the PREVIOUS session in the evening —
# 95% of 18–19h snapshot `open` were yesterday's, and the same payload fed
# market_volume/change_pct (AUDIT-golden-list-20260922 §8, EXEC-PLAN §7.1).
MI_INDEX_BY_DATE_URL = ("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                        "?date={date}&type=ALLBUT0999&response=json")


MI_MARGN_BY_DATE_URL = ("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
                        "?date={date}&selectType=ALL&response=json")


def _parse_margin_by_stock(data) -> dict[str, dict]:
    """Pure: TWSE MI_MARGN(date=…, selectType=ALL) 融資融券彙總 → {code: {balance, change}}(張).

    Row layout: 0 代號 1 名稱 | 融資 2 買進 3 賣出 4 現金償還 5 前日餘額 6 今日餘額 7 限額 |
    融券 8..13 | 14 資券互抵 15 註記. Only 融資 (margin long) is used — that is the
    retail-leverage signal W4 reads. ETFs (00xx) skipped, as in the other parsers.
    """
    out: dict[str, dict] = {}
    for t in (data or {}).get("tables") or []:
        f = t.get("fields") or []
        if not f or f[0] != "代號" or len(f) < 8:
            continue
        for r in t.get("data") or []:
            code = str(r[0]).strip()
            if not code or code.startswith("00") or len(r) < 7:
                continue
            prev, today = parse_int_safe(r[5]), parse_int_safe(r[6])
            out[code] = {"balance": today, "change": today - prev}
    return out


def fetch_margin_by_date(yyyymmdd: str) -> dict:
    """Per-stock 融資餘額 for exactly `yyyymmdd`; raises unless TWSE confirms that date."""
    log(f"[twse] fetching MI_MARGN {yyyymmdd} (per-stock margin)...")
    data = http_get_json(MI_MARGN_BY_DATE_URL.format(date=yyyymmdd), timeout=30)
    if data.get("stat") != "OK" or str(data.get("date")) != yyyymmdd:
        raise ValueError(f"MI_MARGN {yyyymmdd}: stat={data.get('stat')} date={data.get('date')}")
    rows = _parse_margin_by_stock(data)
    if not rows:
        raise ValueError(f"MI_MARGN {yyyymmdd}: no per-stock rows parsed")
    log(f"[twse] MI_MARGN {yyyymmdd}: {len(rows)} stocks")
    return {"date": yyyymmdd, "rows": rows}


def _parse_mi_index_quotes(data) -> tuple[dict[str, float], dict[str, dict]]:
    """Pure: TWSE MI_INDEX(date=…) → ({code: open}, {code: {vol張, close, chgPct真%, chgAmt元}}).

    Same shapes as _parse_open_map/_parse_market_quotes. ETFs (00xx) skipped; a
    blank open ("--", suspended) is simply absent. The sign of the move lives in
    the "漲跌(+/-)" column as HTML (<p style= color:green>-</p>).
    """
    open_map: dict[str, float] = {}
    quotes: dict[str, dict] = {}
    for t in (data or {}).get("tables") or []:
        f = t.get("fields") or []
        if not f or f[0] != "證券代號":
            continue
        need = ("開盤價", "收盤價", "成交股數", "漲跌(+/-)", "漲跌價差")
        if not all(k in f for k in need):
            continue
        i = {k: f.index(k) for k in need}
        for r in t.get("data") or []:
            code = str(r[0]).strip()
            if not code or code.startswith("00"):
                continue
            op = parse_float_safe(r[i["開盤價"]])
            if op:
                open_map[code] = op
            close = parse_float_safe(r[i["收盤價"]])
            if not close:
                continue
            chg = parse_float_safe(r[i["漲跌價差"]]) * (-1 if "-" in str(r[i["漲跌(+/-)"]]) else 1)
            prev_close = close - chg
            quotes[code] = {
                "vol":    int(round(parse_int_safe(r[i["成交股數"]]) / 1000.0)),  # 張
                "close":  close,
                "chgPct": round(chg / prev_close * 100, 2) if prev_close else 0.0,
                "chgAmt": chg,
            }
    return open_map, quotes


def fetch_quotes_by_date(yyyymmdd: str) -> dict:
    """Session-dated quotes for exactly `yyyymmdd`; raises unless TWSE confirms that date."""
    log(f"[twse] fetching MI_INDEX {yyyymmdd} (session-dated open/close/volume)...")
    data = http_get_json(MI_INDEX_BY_DATE_URL.format(date=yyyymmdd), timeout=30)
    if data.get("stat") != "OK" or str(data.get("date")) != yyyymmdd:
        raise ValueError(f"MI_INDEX {yyyymmdd}: stat={data.get('stat')} date={data.get('date')}")
    open_map, quotes = _parse_mi_index_quotes(data)
    if not open_map:
        raise ValueError(f"MI_INDEX {yyyymmdd}: no open prices parsed")
    log(f"[twse] MI_INDEX {yyyymmdd}: {len(open_map)} opens, {len(quotes)} quotes")
    return {"date": yyyymmdd, "openPrices": open_map, "marketQuotes": quotes}


def _parse_open_map(data) -> dict[str, float]:
    """Pure: TWSE STOCK_DAY_ALL rows → {code: opening_price}. ETFs (00xx) skipped."""
    out: dict[str, float] = {}
    for item in data or []:
        code = str(item.get("Code") or item.get("證券代號", "")).strip()
        op = parse_float_safe(item.get("OpeningPrice") or item.get("開盤價", 0))
        if code and not code.startswith("00") and op:
            out[code] = op
    return out


def _parse_market_quotes(data) -> dict[str, dict]:
    """Pure: TWSE STOCK_DAY_ALL rows → {code: {vol(張), close, chgPct(真%), chgAmt(元)}}.

    A2 fix (2026-07-03): full-market volume so market_volume coverage isn't
    limited to the volume-top20 list, plus an authoritative real-percent
    change (TWSE "Change" is the NT$ move — same mislabel 730fd4d fixed).
    ETFs (00xx) skipped, consistent with _parse_open_map.
    """
    out: dict[str, dict] = {}
    for item in data or []:
        code = str(item.get("Code") or item.get("證券代號", "")).strip()
        if not code or code.startswith("00"):
            continue
        vol_shares = parse_int_safe(item.get("TradeVolume") or item.get("成交股數", 0))
        close = parse_float_safe(item.get("ClosingPrice") or item.get("收盤價", 0))
        chg = parse_float_safe(item.get("Change") or item.get("漲跌價差", 0))
        if not close:
            continue
        prev_close = close - chg
        chg_pct = round(chg / prev_close * 100, 2) if prev_close else 0.0
        out[code] = {
            "vol":    int(round(vol_shares / 1000.0)),  # 張
            "close":  close,
            "chgPct": chg_pct,
            "chgAmt": chg,
        }
    return out


def fetch_open_map():
    """Fetch STOCK_DAY_ALL once; return (open_map, market_quotes)."""
    log("[twse] fetching STOCK_DAY_ALL (open prices + market quotes)...")
    data = http_get_json(STOCK_DAY_ALL_URL, timeout=30)
    out = _parse_open_map(data)
    quotes = _parse_market_quotes(data)
    log(f"[twse] STOCK_DAY_ALL: {len(out)} open prices, {len(quotes)} market quotes")
    return out, quotes


def fetch_volume_top20():
    log("[twse] fetching MI_INDEX20...")
    data = http_get_json(MI_INDEX20_URL, timeout=20)
    rows = []
    trading_date = None
    for item in data:
        if not trading_date:
            trading_date = str(item.get("Date") or item.get("資料日期", "")).strip()
        # Try English keys first, fall back to Chinese keys
        code  = str(item.get("Code") or item.get("股票代號", "")).strip()
        name  = str(item.get("Name") or item.get("股票名稱", "")).strip()
        vol   = parse_int_safe(item.get("TradeVolume") or item.get("成交股數", 0))
        close = parse_float_safe(item.get("ClosingPrice") or item.get("收盤價", 0))
        # TWSE "Change" (漲跌價差) is the ABSOLUTE NT$ move, not a percentage.
        # Storing it directly as chgPct made 1000+ NT$ stocks (e.g. 國巨 2327,
        # +100 NT$ ≈ +9.6%) read as "100%". Convert to a real percent here.
        chg   = parse_float_safe(item.get("Change") or item.get("漲跌價差", 0))
        prev_close = close - chg
        chg_pct = round(chg / prev_close * 100, 2) if prev_close else 0.0
        if code and not code.startswith("00"):  # filter ETFs
            rows.append({"code": code, "name": name, "todayVol": vol, "close": close,
                         "chgPct": chg_pct, "chgAmt": chg})
    log(f"[twse] MI_INDEX20: {len(rows)} non-ETF stocks (tradingDate={trading_date})")
    return rows, trading_date


def fetch_margin():
    log("[twse] fetching MI_MARGN...")
    data = http_get_json(MI_MARGN_URL, timeout=20)
    total_margin = 0
    for item in data:
        # Chinese key: 融資今日餘額
        bal = parse_int_safe(item.get("MarginPurchaseBalance") or item.get("融資今日餘額", 0))
        total_margin += bal
    log(f"[twse] total margin balance: {total_margin:,} lots")
    return {"marginBalance": total_margin}


def fetch():
    result = {}
    try:
        rows, trading_date = fetch_volume_top20()
        result["volTop20"] = rows
        result["tradingDate"] = trading_date  # "20260515" format from TWSE
    except Exception as e:
        log(f"[twse] MI_INDEX20 failed: {e}")
        result["volTop20"] = []
        result["volTop20Error"] = str(e)
    try:
        result["marketMeta"] = fetch_margin()
    except Exception as e:
        log(f"[twse] MI_MARGN failed: {e}")
        result["marketMeta"] = {}
        result["marketMetaError"] = str(e)
    try:
        result["openPrices"], result["marketQuotes"] = fetch_open_map()
    except Exception as e:
        log(f"[twse] STOCK_DAY_ALL failed: {e}")
        result["openPrices"] = {}
        result["marketQuotes"] = {}
        result["openPricesError"] = str(e)
    return result


if __name__ == "__main__":
    try:
        result = fetch()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        log(f"[twse] FAILED: {e}")
        print(json.dumps({"error": str(e), "volTop20": [], "marketMeta": {}}))
        sys.exit(1)
