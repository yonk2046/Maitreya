"""SCD Engine — Market Pulse Fetcher

Fetches macro market indicators and writes to:
    <project_root>/data/market_pulse.json

Data sources:
  TAIEX (加權指數)       — TWSE after-hours MI_INDEX API
  TX Futures (台指期)    — TAIFEX open data API
  三大法人台指期未平倉     — TAIFEX open data API

Output schema (data/market_pulse.json):
{
  "fetched_at":  "2026-05-29T19:05:00+08:00",
  "date":        "2026-05-29",
  "taiex": {
    "close":       22150.23,
    "change":      125.45,
    "change_pct":  0.57,
    "volume_b_ntd": 3842.5,   # 成交金額 億元
    "source":      "twse-MI_INDEX"
  },
  "tx_futures": {
    "close":       22180,
    "change":      130,
    "basis":       29.77,     # futures close - taiex close (正=正價差)
    "open_interest": 62150,   # 未平倉口數
    "oi_change":   1240,      # 未平倉變化
    "volume":      85234,     # 成交口數
    "source":      "taifex-openapi"
  },
  "institutional_futures": {
    "foreign":          {"net_oi": 25431, "oi_change": 1240},
    "investment_trust": {"net_oi": 3200,  "oi_change": -80},
    "dealer":           {"net_oi": -1500, "oi_change": 200},
    "source":           "taifex-openapi"
  },
  "breadth": {
    "universe":              "twse_listed_stocks",   # C1: 母體宣告 — 純上市股票，不含 ETF/DR/權證
    "advancers":              411,
    "advancers_limit_up":     22,
    "decliners":               552,
    "decliners_limit_down":   2,
    "unchanged":              74,
    "unmatched":              0,
    "no_comparison":          41,
    "total":                  1078,
    "source":                 "twse-MI_INDEX-ALLBUT0999"
  },
  "errors": []
}

Market breadth (全市場漲跌家數) is fetched from the same TWSE MI_INDEX
after-hours endpoint used for TAIEX, with `type=ALLBUT0999` — see
docs/architecture_research/spikes/SPIKE-breadth-source.md for the source
survey. The `股票` column (pure TWSE-listed stocks) is used, NOT `整體市場`
(which mixes ETF/DR/warrants and is not a valid "market" universe — C1
命名即語意: the field must declare which population it counts). Adding TPEX
(上櫃) later is an *additive* new scope key, not a redefinition of this one.

Archiving: every successful run also writes a WORM per-date snapshot to
    <project_root>/data/market_pulse/YYYY-MM-DD.json
An existing archive file for a date is never overwritten (write-once) — this
is what makes historical backfill (`--date YYYYMMDD`) safe to re-run.
`data/market_pulse.json` continues to hold the latest fetch unconditionally
(the viewer reads this path and must not break).

CLI:
    python tools/fetch_market_pulse.py
    python tools/fetch_market_pulse.py --dry-run
    python tools/fetch_market_pulse.py --date 2026-05-29
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

# ── Path resolution ──────────────────────────────────────────────────────────
_HERE = pathlib.Path(__file__).resolve().parent          # tools/
_PROJECT = _HERE.parent                                  # Ai stock/
_DATA_DIR = _PROJECT / "data"

TW_TZ = timezone(timedelta(hours=8))


def _project_root() -> pathlib.Path:
    env = pathlib.Path(__file__).resolve().parent.parent    # SCD engine/
    return env


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get_json(url: str, timeout: int = 12, referer: str = "https://www.twse.com.tw/") -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if not raw.strip():
        raise ValueError("empty response")
    return json.loads(raw.decode("utf-8-sig"))


# ── Yahoo Finance — TAIEX fallback ───────────────────────────────────────────

_TAIEX_CACHE_PATH = _PROJECT / "data" / ".taiex_cache.json"


def _save_taiex_cache(result: dict) -> None:
    try:
        _TAIEX_CACHE_PATH.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_taiex_cache() -> dict | None:
    try:
        if _TAIEX_CACHE_PATH.exists():
            d = json.loads(_TAIEX_CACHE_PATH.read_text(encoding="utf-8"))
            if d.get("close"):
                d["source"] = d.get("source", "cache") + " (cached)"
                return d
    except Exception:
        pass
    return None



# ── TWSE — TAIEX ─────────────────────────────────────────────────────────────

def _fetch_taiex(date_str: str | None = None) -> dict[str, Any]:
    """Fetch 加權股價指數 close.

    Sources tried in order:
      1. Yahoo Finance ^TWII  (most reliable, rate-limited under heavy testing)
      2. TWSE STOCK_DAY_INDEX  (after-hours index endpoint)
      3. Local cache           (last successful fetch)
    """
    if date_str is None:
        date_str = datetime.now(TW_TZ).strftime("%Y%m%d")

    # 1. Yahoo Finance — try multiple endpoints and add cookie to bypass rate limit
    yf_urls = [
        f"https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range=2d",
        f"https://query2.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range=2d",
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/%5ETWII?modules=price",
    ]
    for url in yf_urls:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://finance.yahoo.com/quote/%5ETWII/",
                "Cookie": "A1=d=AQABBFu; A3=d=AQABBFu",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            if not raw.strip():
                continue
            yf = json.loads(raw.decode("utf-8-sig"))
            # v8 chart response
            if "chart" in yf:
                meta  = yf["chart"]["result"][0]["meta"]
                close = meta.get("regularMarketPrice") or meta.get("previousClose")
                prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
            # v10 quoteSummary response
            elif "quoteSummary" in yf:
                p = yf["quoteSummary"]["result"][0]["price"]
                close = p.get("regularMarketPrice", {}).get("raw")
                prev  = p.get("regularMarketPreviousClose", {}).get("raw")
                meta  = {}
            else:
                continue
            if not close:
                continue
            change = round(close - prev, 2) if (close and prev) else None
            change_pct = round(change / prev * 100, 2) if (change and prev) else None
            vol_yf = meta.get("regularMarketVolume") if meta else None
            vol_b  = round(vol_yf / 1e8, 1) if vol_yf else None
            result = {"close": close, "change": change,
                      "change_pct": change_pct, "volume_b_ntd": vol_b,
                      "source": "yahoo-finance"}
            _save_taiex_cache(result)
            return result
        except Exception:
            time.sleep(2)

    print("  [taiex] Yahoo failed, trying TWSE MI_INDEX tables…", flush=True)

    # 2. TWSE MI_INDEX — tables format (most reliable)
    try:
        mi = _get_json(
            f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            f"?response=json&date={date_str}&type=IND",
            referer="https://www.twse.com.tw/",
        )
        if mi.get("stat") == "OK":
            for table in mi.get("tables", []):
                for row in table.get("data", []):
                    if "發行量加權股價指數" in (row[0] if row else ""):
                        def _n(s):
                            try: return float(str(s).replace(",", "").strip())
                            except: return None
                        close = _n(row[1]) if len(row) > 1 else None
                        change = _n(row[3]) if len(row) > 3 else None
                        change_pct = _n(row[4]) if len(row) > 4 else None
                        if close and close > 5000:
                            result = {"close": close, "change": change,
                                      "change_pct": change_pct, "volume_b_ntd": None,
                                      "source": "twse-MI_INDEX-tables"}
                            _save_taiex_cache(result)
                            return result
    except Exception as e:
        print(f"  [taiex] MI_INDEX tables failed: {e}", flush=True)

    print("  [taiex] trying TWSE STOCK_DAY_INDEX…", flush=True)

    # 3. TWSE STOCK_DAY_INDEX
    try:
        sd = _get_json(
            f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_INDEX"
            f"?response=json&date={date_str}"
        )
        if sd.get("stat") == "OK":
            fields = sd.get("fields", []) or []
            for row in sd.get("data", []):
                if len(row) < 2:
                    continue
                def _n(s):
                    try: return float(str(s).replace(",","").replace("+","").strip())
                    except: return None
                # Try to find the 發行量加權股價指數 row
                name = row[0] if row else ""
                if "加權" in name or (len(row) > 1 and _n(row[1]) and _n(row[1]) > 5000):
                    close = _n(row[1]) if len(row) > 1 else None
                    change = _n(row[2]) if len(row) > 2 else None
                    change_pct = _n(row[3]) if len(row) > 3 else None
                    if close and close > 5000:
                        result = {"close": close, "change": change,
                                  "change_pct": change_pct, "volume_b_ntd": None,
                                  "source": "twse-STOCK_DAY_INDEX"}
                        _save_taiex_cache(result)
                        return result
    except Exception as e:
        print(f"  [taiex] STOCK_DAY_INDEX failed: {e}", flush=True)

    # 3. Cache fallback
    cached = _load_taiex_cache()
    if cached:
        print("  [taiex] using cached value", flush=True)
        return cached

    return {"error": "all TAIEX sources failed", "source": "twse"}


# ── TWSE — 全市場漲跌家數 (market breadth) ───────────────────────────────────
#
# C1 命名即語意: this scope is explicitly the TWSE-*listed-stocks* universe.
# It must NOT be silently redefined to include TPEX (上櫃) or any other venue
# — that is an additive new scope key (e.g. a future `breadth_tpex`), never a
# change to what `twse_listed_stocks` means (C4 一資料一語意).
_BREADTH_UNIVERSE = "twse_listed_stocks"

# TWSE cells look like "411(22)" (count + parenthesised limit-up/limit-down
# subset) or a bare "74" (no parenthetical). Thousands separators allowed.
_BREADTH_CELL_RE = re.compile(r"^([\d,]+)(?:\(([\d,]+)\))?$")

# 漲跌證券數合計 row label (col 0) → output key.
_BREADTH_LABEL_KEY = {
    "上漲(漲停)": "advancers",
    "下跌(跌停)": "decliners",
    "持平":       "unchanged",
    "未成交":     "unmatched",
    "無比價":     "no_comparison",
}


def _parse_breadth_cell(s: str) -> tuple[int, int | None]:
    """Parse a TWSE 漲跌證券數合計 cell, e.g. '411(22)' or '74'.

    Returns (count, sub_count) where sub_count is the parenthesised
    limit-up/limit-down subset, or None when the cell has no parenthesis.

    Strict + loud: raises ValueError on anything that doesn't match the
    expected shape. Callers MUST NOT catch this and coerce to 0 — a failed
    parse belongs in `errors`, never silently fabricated as a zero value
    (as-was 原則, C10: an unreadable observation is not the same as "no
    advancers today").
    """
    m = _BREADTH_CELL_RE.match(s.strip())
    if not m:
        raise ValueError(f"cannot parse breadth cell: {s!r}")
    count = int(m.group(1).replace(",", ""))
    sub = int(m.group(2).replace(",", "")) if m.group(2) else None
    return count, sub


def _fetch_market_breadth(date_str: str) -> dict[str, Any]:
    """Fetch 全市場漲跌家數 (market breadth) for the TWSE-listed-stock universe.

    Source: TWSE MI_INDEX?type=ALLBUT0999 → table titled 漲跌證券數合計 →
    the `股票` column (NOT `整體市場`, which mixes ETF/DR/warrants — see
    SPIKE-breadth-source.md §2 候選A). Shares the same base endpoint,
    `_get_json` helper, and `date=YYYYMMDD` parameter format as `_fetch_taiex`
    fallback #2, so historical backfill via `--date` works the same way.

    On any failure this returns a dict containing "error" — it never
    fabricates zeros for missing/unparseable fields.
    """
    base = {"universe": _BREADTH_UNIVERSE, "source": "twse-MI_INDEX-ALLBUT0999"}

    try:
        mi = _get_json(
            f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            f"?response=json&date={date_str}&type=ALLBUT0999",
            referer="https://www.twse.com.tw/",
        )
    except Exception as e:
        return {**base, "error": f"request failed: {e}"}

    if mi.get("stat") != "OK":
        return {**base, "error": f"stat != OK: {mi.get('stat')!r}"}

    table = None
    for t in mi.get("tables", []):
        if "漲跌證券數合計" in (t.get("title") or ""):
            table = t
            break
    if table is None:
        return {**base, "error": "漲跌證券數合計 table not found in response"}

    fields = table.get("fields", []) or []
    try:
        stock_idx = fields.index("股票")
    except ValueError:
        return {**base, "error": f"'股票' column not found in fields={fields}"}

    row_map: dict[str, str] = {}
    for row in table.get("data", []) or []:
        if len(row) <= stock_idx:
            continue
        row_map[row[0]] = row[stock_idx]

    out: dict[str, Any] = dict(base)
    parse_errors: list[str] = []
    for label, key in _BREADTH_LABEL_KEY.items():
        cell = row_map.get(label)
        if cell is None:
            parse_errors.append(f"missing row for {label!r}")
            continue
        try:
            count, sub = _parse_breadth_cell(cell)
        except ValueError as e:
            parse_errors.append(str(e))
            continue
        out[key] = count
        if key == "advancers":
            out["advancers_limit_up"] = sub          # None if TWSE omits the paren group
        elif key == "decliners":
            out["decliners_limit_down"] = sub

    if parse_errors:
        # Loud failure: report exactly what didn't parse, don't guess at 0.
        out["error"] = "; ".join(parse_errors)
        return out

    out["total"] = (
        out["advancers"] + out["decliners"] + out["unchanged"]
        + out["unmatched"] + out["no_comparison"]
    )
    return out


# ── TAIFEX — TX Futures ───────────────────────────────────────────────────────

def _get_html(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 SCD-Engine/1.0",
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://www.taifex.com.tw/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    # Try UTF-8, fallback to big5
    for enc in ("utf-8", "big5", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean_cell(c: str) -> str:
    c = re.sub(r"<[^>]+>", "", c)
    return c.replace("\xa0", "").replace("　", "").strip()


def _parse_html_rows(html: str) -> list[list[str]]:
    """Return all <tr> rows as lists of cleaned cell text."""
    result = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
        cells = [_clean_cell(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.DOTALL | re.IGNORECASE)]
        cells = [c for c in cells if c]  # drop empty
        if cells:
            result.append(cells)
    return result


def _rows_to_dicts(all_rows: list[list[str]], header_hint: list[str]) -> list[dict]:
    """Find the header row matching hint keywords, zip subsequent rows."""
    header: list[str] = []
    out: list[dict] = []
    for row in all_rows:
        if not header:
            if sum(1 for h in header_hint if any(h in c for c in row)) >= 2:
                header = row
            continue
        if len(row) >= max(3, len(header) // 2):
            # Pad or trim to header length
            padded = (row + [""] * len(header))[: len(header)]
            out.append(dict(zip(header, padded)))
    return out


def _taifex_date(date_str: str | None = None) -> str:
    """Return date in TAIFEX query format YYYY/MM/DD."""
    if date_str is None:
        return datetime.now(TW_TZ).strftime("%Y/%m/%d")
    # Accept YYYYMMDD or YYYY-MM-DD
    d = date_str.replace("-", "").replace("/", "")
    return f"{d[:4]}/{d[4:6]}/{d[6:8]}"


def _get_csv(url: str, timeout: int = 15) -> list[list[str]]:
    """Fetch a CSV from TAIFEX and return as list of rows (list of str)."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.taifex.com.tw/",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    text = ""
    for enc in ("utf-8-sig", "big5", "cp950", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Simple CSV split (TAIFEX CSVs rarely have quoted commas)
        rows.append([c.strip() for c in line.split(",")])
    return rows


def _fetch_tx_futures_html() -> dict[str, Any]:
    """CSV fallback: download TX daily data from TAIFEX CSV endpoint.

    TAIFEX CSV column order (typical):
      交易日期,商品名稱,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未平倉口數
    """
    qdate = datetime.now(TW_TZ).strftime("%Y/%m/%d")
    csv_rows: list = []
    for cid in ("TX", "TXF", ""):
        suffix = f"&commodity_id={cid}" if cid else ""
        url = (
            f"https://www.taifex.com.tw/cht/3/futDataDown"
            f"?down_type=1{suffix}&queryStartDate={qdate}&queryEndDate={qdate}"
        )
        try:
            rows = _get_csv(url)
            if len(rows) > 2:   # more than just header rows
                csv_rows = rows
                break
        except Exception:
            pass
    if not csv_rows:
        return {"error": "CSV fallback failed — no data returned", "source": "taifex-csv"}

    def _n(v: str) -> float | None:
        v = str(v).replace(",", "").replace("+", "").strip()
        if not v or v in ("--", "－", "-"):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    # Find header row then map data rows
    # CSV format: 交易日期,商品名稱,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未平倉口數
    header: list[str] = []
    for row in csv_rows:
        if not header:
            if any("商品" in c or "收盤" in c for c in row):
                header = row
            continue
        if len(row) < 4:
            continue
        d = dict(zip(header, row)) if header else {}
        name = d.get("商品名稱", row[1] if len(row) > 1 else "")
        # Match 臺股期貨 or TX or TXF
        if not any(k in name for k in ("臺股", "TX", "TXF")):
            continue
        # Use dict if we have a header, else positional
        # Positional: date(0) name(1) month(2) open(3) high(4) low(5) close(6) chg(7) chg%(8) vol(9) settle(10) oi(11)
        close  = _n(d.get("收盤價", row[6] if len(row) > 6 else ""))
        change = _n(d.get("漲跌價", row[7] if len(row) > 7 else ""))
        oi     = _n(d.get("未平倉口數", row[11] if len(row) > 11 else ""))
        vol    = _n(d.get("成交量", row[9] if len(row) > 9 else ""))
        return {"close": close or _n(d.get("結算價", row[10] if len(row) > 10 else "")),
                "change": change, "open_interest": oi, "oi_change": None,
                "volume": vol, "source": "taifex-csv"}

    return {"error": "TX not found in CSV", "source": "taifex-csv"}


_TAIFEX_REFERER = "https://www.taifex.com.tw/"


def _taifex_json(url: str) -> Any:
    return _get_json(url, referer=_TAIFEX_REFERER)


def _fetch_tx_futures(date_str: str | None = None) -> dict[str, Any]:
    """Fetch TX (台指期近月) summary from TAIFEX open data API."""
    qdate = _taifex_date(date_str)
    data: list = []

    endpoints = [
        f"https://openapi.taifex.com.tw/v1/DailyFuturesAndOptionsStatistics?queryStartDate={qdate}&queryEndDate={qdate}",
        "https://openapi.taifex.com.tw/v1/DailyFuturesAndOptionsStatistics",
        f"https://openapi.taifex.com.tw/v1/DailyFuturesTrades?queryStartDate={qdate}&queryEndDate={qdate}",
        "https://openapi.taifex.com.tw/v1/DailyFuturesTrades",
    ]
    for url in endpoints:
        try:
            result = _taifex_json(url)
            if isinstance(result, list) and len(result) > 0:
                data = result
                break
        except Exception:
            pass

    # Final fallback: HTML scrape
    if not data:
        return _fetch_tx_futures_html()

    # Find TX records (商品代碼 = TX, 近月)
    tx_rows = [
        r for r in data
        if r.get("商品代碼", r.get("commodityId", "")) in ("TX", "TXF")
        and "近月" in (r.get("契約月份(週別)", r.get("contractMonth", "")) or "")
    ]

    if not tx_rows:
        # Fallback: any TX row
        tx_rows = [
            r for r in data
            if r.get("商品代碼", r.get("commodityId", "")) in ("TX", "TXF")
        ]

    if not tx_rows:
        return {"error": "TX row not found", "available_products": list({r.get("商品代碼") for r in data[:10]}), "source": "taifex-openapi"}

    row = tx_rows[0]

    def _n(key: str, alt: str = "") -> float | None:
        v = row.get(key, row.get(alt, ""))
        if v in (None, "", "--", "－"):
            return None
        try:
            return float(str(v).replace(",", ""))
        except ValueError:
            return None

    return {
        "close":         _n("收盤價", "settlementPrice"),
        "change":        _n("漲跌價", "change"),
        "open_interest": _n("未平倉口數", "openInterest"),
        "oi_change":     _n("未平倉口數增減", "openInterestChange"),
        "volume":        _n("成交口數", "volume"),
        "source":        "taifex-openapi",
    }


# ── TAIFEX — 三大法人台指期未平倉 ────────────────────────────────────────────

def _fetch_institutional_futures_html() -> dict[str, Any]:
    """CSV fallback: download 三大法人台指期未平倉 from TAIFEX CSV endpoint.

    CSV columns (typical):
      日期,商品名稱,身份別,多方交易口數,多方交易契約金額(百萬元),
      空方交易口數,空方交易契約金額(百萬元),多空淨額交易口數,多空淨額交易契約金額(百萬元),
      多方未平倉口數,多方未平倉契約金額(百萬元),空方未平倉口數,空方未平倉契約金額(百萬元),
      多空淨額未平倉口數,多空淨額未平倉契約金額(百萬元)
    """
    qdate = datetime.now(TW_TZ).strftime("%Y/%m/%d")
    url = (
        f"https://www.taifex.com.tw/cht/3/futContractsDateDown"
        f"?queryStartDate={qdate}&queryEndDate={qdate}&commodity_id=TX"
    )
    try:
        csv_rows = _get_csv(url)
    except Exception as e:
        return {"error": f"CSV fallback failed: {e}", "source": "taifex-csv"}

    identity_map = {
        "外資": "foreign", "外資及陸資": "foreign",
        "投信": "investment_trust",
        "自營商": "dealer", "自營商(避險)": "dealer",
    }

    def _int(v: str) -> int | None:
        v = str(v).replace(",", "").replace("+", "").strip()
        if not v or v in ("--", "－", "-"):
            return None
        try:
            return int(float(v))
        except ValueError:
            return None

    result: dict[str, Any] = {"source": "taifex-csv"}
    header: list[str] = []

    for row in csv_rows:
        if not header:
            if any("身份" in c or "多方" in c for c in row):
                header = row
            continue
        if len(row) < 5:
            continue
        d = dict(zip(header, row)) if header else {}

        identity = d.get("身份別", row[2] if len(row) > 2 else "").strip()
        key = identity_map.get(identity)
        if not key or key in result:
            continue

        # Positional: date(0) product(1) identity(2) buy_tx(3) buy_amt(4) sell_tx(5) sell_amt(6)
        #             net_tx(7) net_amt(8) long_oi(9) long_oi_amt(10) short_oi(11) short_oi_amt(12)
        #             net_oi(13) net_oi_amt(14)
        net_oi = _int(d.get("多空淨額未平倉口數", row[13] if len(row) > 13 else ""))
        if net_oi is None:
            long_v  = _int(d.get("多方未平倉口數", row[9]  if len(row) > 9  else "")) or 0
            short_v = _int(d.get("空方未平倉口數", row[11] if len(row) > 11 else "")) or 0
            net_oi  = long_v - short_v if (long_v or short_v) else None

        result[key] = {"net_oi": net_oi, "oi_change": None}

    if len(result) <= 1:
        return {"error": "三大法人 TX not found in CSV", "source": "taifex-csv"}

    return result


def _fetch_institutional_futures(date_str: str | None = None) -> dict[str, Any]:
    """Fetch 三大法人台指期未平倉 from TAIFEX open data."""
    qdate = _taifex_date(date_str)
    data: list = []

    endpoints = [
        f"https://openapi.taifex.com.tw/v1/DailyForeignInstitutionalInvestorsFuturesAndOptions?queryStartDate={qdate}&queryEndDate={qdate}",
        "https://openapi.taifex.com.tw/v1/DailyForeignInstitutionalInvestorsFuturesAndOptions",
        f"https://openapi.taifex.com.tw/v1/FuturesAndOptionsOpenInterestLargeTraders?queryStartDate={qdate}&queryEndDate={qdate}",
        "https://openapi.taifex.com.tw/v1/FuturesAndOptionsOpenInterestLargeTraders",
    ]
    for url in endpoints:
        try:
            result = _taifex_json(url)
            if isinstance(result, list) and len(result) > 0:
                data = result
                break
        except Exception:
            pass

    # Final fallback: HTML scrape
    if not data:
        return _fetch_institutional_futures_html()

    # Filter to 台指期 (TX) 未平倉
    tx_rows = [
        r for r in data
        if r.get("商品名稱", r.get("commodityName", "")) in ("臺股期貨", "台指期", "TX")
        or r.get("商品代碼", r.get("commodityId", "")) in ("TX", "TXF")
    ]

    if not tx_rows:
        # Broader match
        tx_rows = [r for r in data if "臺股" in r.get("商品名稱", "") or "台股" in r.get("商品名稱", "")]

    def _net(row: dict, long_key: str, short_key: str) -> int | None:
        def n(k: str) -> int:
            try:
                return int(str(row.get(k, "0")).replace(",", "") or "0")
            except ValueError:
                return 0
        long_v  = n(long_key)
        short_v = n(short_key)
        return long_v - short_v if (long_v or short_v) else None

    result: dict[str, Any] = {"source": "taifex-openapi"}

    identity_map = {
        "外資": "foreign",
        "外資及陸資": "foreign",
        "投信": "investment_trust",
        "自營商": "dealer",
        "自營商(避險)": "dealer",
    }

    for row in tx_rows:
        identity = row.get("身份別", row.get("identity", ""))
        key = identity_map.get(identity)
        if key and key not in result:
            # Try standard TAIFEX open API field names
            net_oi = _net(
                row,
                "多方未平倉口數", "空方未平倉口數",
            )
            if net_oi is None:
                net_oi = _net(row, "多方口數", "空方口數")
            oi_chg = _net(row, "多方未平倉口數增減", "空方未平倉口數增減")

            result[key] = {
                "net_oi":    net_oi,
                "oi_change": oi_chg,
            }

    return result


# ── Per-date archive error detection (2026-07-14 事故後修法) ──────────────────
# 事故:11:46 盤中補跑打到 TWSE MI_INDEX 拿到「很抱歉，沒有符合條件的資料！」,
# 帶 error 的 breadth 被 WORM 規則寫死進 per-date 檔,傍晚正常抓取被擋住不能
# 覆寫 → 當日 obs_market_breadth 全 null。修法:WORM 只保護「乾淨」檔案;
# 帶 error 的既有檔案可以被之後的乾淨抓取升級覆寫。

def _pulse_has_error(pulse: dict[str, Any]) -> bool:
    """True iff this market-pulse result carries a fetch error — either the
    top-level errors[] is non-empty, or breadth itself carries an "error" key
    (the field the trading-day oracle reads). Drives the per-date WORM rule:
    only a clean (error-free) snapshot earns write-once protection.
    """
    if pulse.get("errors"):
        return True
    breadth = pulse.get("breadth")
    if isinstance(breadth, dict) and "error" in breadth:
        return True
    return False


def _archived_pulse_has_error(path: pathlib.Path) -> bool:
    """Like _pulse_has_error but reads an existing on-disk archive file.
    Any read/parse failure is conservatively treated as "has error" so a
    later clean fetch is allowed to repair an unreadable archive rather than
    being permanently blocked by it.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    return _pulse_has_error(data)


# ── Build + write ─────────────────────────────────────────────────────────────

def fetch_and_write(
    dry_run: bool = False,
    date_str: str | None = None,
    out_path: pathlib.Path | None = None,
    archive_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    now_tw = datetime.now(TW_TZ)
    if date_str is None:
        date_str = now_tw.strftime("%Y-%m-%d")

    twse_date = date_str.replace("-", "")

    errors: list[str] = []

    print(f"[market-pulse] fetching TAIEX ({date_str})…", flush=True)
    taiex = _fetch_taiex(twse_date)
    if "error" in taiex:
        errors.append(f"taiex: {taiex['error']}")
        print(f"  ⚠  TAIEX error: {taiex['error']}", flush=True)
    else:
        close = taiex.get("close", "?")
        chg   = taiex.get("change", "?")
        print(f"  ✓  TAIEX {close:,.2f}  {chg:+.2f}" if isinstance(close, float) else f"  ✓  TAIEX {close}", flush=True)

    print("[market-pulse] fetching TX futures…", flush=True)
    tx = _fetch_tx_futures(date_str)
    if "error" in tx:
        errors.append(f"tx_futures: {tx['error']}")
        print(f"  ⚠  TX error: {tx['error']}", flush=True)
    else:
        print(f"  ✓  TX close={tx.get('close')}  OI={tx.get('open_interest')}", flush=True)

    # Compute basis
    if isinstance(taiex.get("close"), (int, float)) and isinstance(tx.get("close"), (int, float)):
        tx["basis"] = round(tx["close"] - taiex["close"], 2)

    print("[market-pulse] fetching 三大法人台指期未平倉…", flush=True)
    inst = _fetch_institutional_futures(date_str)
    if "error" in inst:
        errors.append(f"institutional: {inst['error']}")
        print(f"  ⚠  Institutional error: {inst['error']}", flush=True)
    else:
        fii = inst.get("foreign", {})
        print(f"  ✓  外資台指期淨部位: {fii.get('net_oi')}", flush=True)

    print("[market-pulse] fetching 全市場漲跌家數 (market breadth)…", flush=True)
    breadth = _fetch_market_breadth(twse_date)
    if "error" in breadth:
        errors.append(f"breadth: {breadth['error']}")
        print(f"  ⚠  Breadth error: {breadth['error']}", flush=True)
    else:
        print(
            f"  ✓  Breadth[{breadth.get('universe')}] "
            f"advancers={breadth.get('advancers')} decliners={breadth.get('decliners')} "
            f"unchanged={breadth.get('unchanged')} total={breadth.get('total')}",
            flush=True,
        )

    pulse: dict[str, Any] = {
        "fetched_at":              now_tw.isoformat(timespec="seconds"),
        "date":                    date_str,
        "taiex":                   taiex,
        "tx_futures":              tx,
        "institutional_futures":   inst,
        "breadth":                 breadth,
        "errors":                  errors,
    }

    if dry_run:
        print("\n[dry-run] would write:")
        print(json.dumps(pulse, ensure_ascii=False, indent=2))
        return pulse

    if out_path is None:
        out_path = _project_root() / "data" / "market_pulse.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(pulse, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[market-pulse] ✓ written → {out_path}", flush=True)

    # WORM per-date archive — data/market_pulse/YYYY-MM-DD.json.
    # Write-once, but only a CLEAN archive earns the protection:
    #   existing clean, new clean   → WORM holds, not overwritten (unchanged).
    #   existing clean, new errored → WORM holds, not overwritten (never let
    #                                  a worse/errored fetch clobber a good one).
    #   existing errored, new clean → upgrade allowed (error→clean upgrade) —
    #                                  this is the 2026-07-14 fix: a stray
    #                                  intraday error must not permanently
    #                                  block the honest post-close fetch.
    #   existing errored, new errored → WORM holds (the attempt is already
    #                                  honestly recorded; nothing better to write).
    #   no existing archive         → always write (honest record of the attempt).
    if archive_dir is None:
        archive_dir = _project_root() / "data" / "market_pulse"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{date_str}.json"
    new_has_error = _pulse_has_error(pulse)
    if not archive_path.exists():
        archive_path.write_text(json.dumps(pulse, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[market-pulse] ✓ archived → {archive_path}", flush=True)
    elif _archived_pulse_has_error(archive_path) and not new_has_error:
        archive_path.write_text(json.dumps(pulse, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[market-pulse] ✓ archive upgraded (error→clean upgrade) → {archive_path}", flush=True)
    else:
        print(f"[market-pulse] per-date archive already exists (WORM, not overwritten) → {archive_path}", flush=True)

    return pulse


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SCD Market Pulse Fetcher — TAIEX + TX + 三大法人")
    ap.add_argument("--dry-run", action="store_true", help="print result, do not write file")
    ap.add_argument("--date",    default=None,        help="YYYY-MM-DD (default: today)")
    args = ap.parse_args(argv)
    fetch_and_write(dry_run=args.dry_run, date_str=args.date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
