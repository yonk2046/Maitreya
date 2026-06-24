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


def _parse_open_map(data) -> dict[str, float]:
    """Pure: TWSE STOCK_DAY_ALL rows → {code: opening_price}. ETFs (00xx) skipped."""
    out: dict[str, float] = {}
    for item in data or []:
        code = str(item.get("Code") or item.get("證券代號", "")).strip()
        op = parse_float_safe(item.get("OpeningPrice") or item.get("開盤價", 0))
        if code and not code.startswith("00") and op:
            out[code] = op
    return out


def fetch_open_map():
    log("[twse] fetching STOCK_DAY_ALL (open prices)...")
    data = http_get_json(STOCK_DAY_ALL_URL, timeout=30)
    out = _parse_open_map(data)
    log(f"[twse] STOCK_DAY_ALL: {len(out)} open prices")
    return out


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
        chg   = parse_float_safe(item.get("Change") or item.get("漲跌價差", 0))
        if code and not code.startswith("00"):  # filter ETFs
            rows.append({"code": code, "name": name, "todayVol": vol, "close": close, "chgPct": chg})
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
        result["openPrices"] = fetch_open_map()
    except Exception as e:
        log(f"[twse] STOCK_DAY_ALL failed: {e}")
        result["openPrices"] = {}
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
