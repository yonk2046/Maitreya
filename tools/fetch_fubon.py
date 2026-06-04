"""Fetch Fubon ZGK_D foreign-investor buy/sell ranking via plain HTTP (BIG5 encoded page).

URL: https://fubon-ebrokerdj.fbs.com.tw/Z/ZG/ZGK_D.djhtm
Output: JSON with topBuy[], topSell[] (each up to 50 entries)
"""

import json
import sys
import re
from _common import http_get, extract_table_rows, is_etf, parse_int_safe, parse_float_safe, log

URL = "https://fubon-ebrokerdj.fbs.com.tw/Z/ZG/ZGK_D.djhtm"

NAME_PATTERN = re.compile(r"^([0-9A-Z]+)(.+)$")


def parse_code_name(s):
    s = (s or "").strip()
    m = NAME_PATTERN.match(s)
    if m:
        return m.group(1), m.group(2)
    return s, ""


def fetch():
    log("[fubon] fetching ZGK_D via plain HTTP (BIG5)...")
    raw = http_get(URL, timeout=30)
    # Fubon pages are BIG5 encoded
    html = raw.decode("big5", errors="replace")
    rows = extract_table_rows(html, min_cells=5)
    log(f"[fubon] extracted {len(rows)} raw rows")

    top_buy = []
    top_sell = []
    for r in rows:
        if len(r) < 10:
            continue
        if "名次" in r[0]:
            continue
        # Buy side
        try:
            rank = int(r[0])
            code, name = parse_code_name(r[1])
            vol = parse_int_safe(r[2])
            close = parse_float_safe(r[3])
            chg = parse_float_safe(r[4])
            if code and not is_etf(code):
                top_buy.append({
                    "rank": rank, "code": code, "name": name,
                    "buyVol": vol, "close": close, "chgPct": chg,
                    "isETF": False,
                })
        except (ValueError, IndexError):
            pass
        # Sell side
        try:
            rank = int(r[5])
            code, name = parse_code_name(r[6])
            vol = parse_int_safe(r[7])
            close = parse_float_safe(r[8])
            chg = parse_float_safe(r[9])
            if code and not is_etf(code):
                top_sell.append({
                    "rank": rank, "code": code, "name": name,
                    "sellVol": abs(vol), "close": close, "chgPct": chg,
                    "isETF": False,
                })
        except (ValueError, IndexError):
            pass

    log(f"[fubon] top_buy={len(top_buy)}  top_sell={len(top_sell)}")
    return {"topBuy": top_buy, "topSell": top_sell}


INSTITUTIONAL_URL = "https://fubon-ebrokerdj.fbs.com.tw/Z/ZG/ZGK_F.djhtm"


def fetch_institutional():
    """Fetch 主力買賣超排行 via ZGK_F (same BIG5 structure as ZGK_D)."""
    log("[fubon-inst] fetching ZGK_F 主力買賣超 via plain HTTP (BIG5)...")
    raw = http_get(INSTITUTIONAL_URL, timeout=30)
    html = raw.decode("big5", errors="replace")
    rows = extract_table_rows(html, min_cells=5)
    log(f"[fubon-inst] extracted {len(rows)} raw rows")

    top_buy = []
    top_sell = []
    for r in rows:
        if len(r) < 10:
            continue
        if "名次" in r[0]:
            continue
        try:
            rank = int(r[0])
            code, name = parse_code_name(r[1])
            vol = parse_int_safe(r[2])
            close = parse_float_safe(r[3])
            chg = parse_float_safe(r[4])
            if code and not is_etf(code) and vol > 0:
                top_buy.append({
                    "rank": rank, "code": code, "name": name,
                    "buyVol": vol, "close": close, "chgPct": chg,
                    "isETF": False,
                })
        except (ValueError, IndexError):
            pass
        try:
            rank = int(r[5])
            code, name = parse_code_name(r[6])
            vol = parse_int_safe(r[7])
            close = parse_float_safe(r[8])
            chg = parse_float_safe(r[9])
            if code and not is_etf(code):
                top_sell.append({
                    "rank": rank, "code": code, "name": name,
                    "sellVol": abs(vol), "close": close, "chgPct": chg,
                    "isETF": False,
                })
        except (ValueError, IndexError):
            pass

    log(f"[fubon-inst] mainForce buy={len(top_buy)}  sell={len(top_sell)}")
    return {"topBuy": top_buy, "topSell": top_sell}


if __name__ == "__main__":
    if "--institutional" in sys.argv or "-i" in sys.argv:
        try:
            result = fetch_institutional()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            log(f"[fubon-inst] FAILED: {e}")
            print(json.dumps({"error": str(e), "topBuy": [], "topSell": []}))
            sys.exit(1)
    else:
        try:
            result = fetch()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            log(f"[fubon] FAILED: {e}")
            print(json.dumps({"error": str(e), "topBuy": [], "topSell": []}))
            sys.exit(1)
