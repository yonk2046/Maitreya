"""Fetch TWSE T86 三大法人買賣超 daily — authoritative full-market data.

Endpoint: https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=YYYYMMDD&selectType=ALL
Returns: full-market per-stock 外資/投信/自營商/三大法人合計 (units: 股, divide by 1000 for 張).

Used in Wave E.4 as cross-verification against Fubon ZGK_D (外資) and ZGK_F (主力).
"""

import json
import sys
from datetime import datetime, timedelta
from _common import http_get_json, parse_int_safe, log

URL_TEMPLATE = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date}&selectType=ALL"

# Verified field indices (2026-05-15 sample):
# 0  證券代號
# 1  證券名稱
# 4  外陸資買賣超股數(不含外資自營商)
# 10 投信買賣超股數
# 11 自營商買賣超股數 (合計)
# 18 三大法人買賣超股數
IDX_CODE = 0
IDX_NAME = 1
IDX_FOREIGN_NET = 4
IDX_TRUST_NET = 10
IDX_PROP_NET = 11
IDX_TOTAL3_NET = 18


def _shares_to_lots(shares):
    """Convert 股 to 張 (1 張 = 1,000 股). Round to nearest integer."""
    if shares is None:
        return 0
    return int(round(shares / 1000.0))


def fetch(date_yyyymmdd=None):
    """Fetch T86 for given trading date (YYYYMMDD). Defaults to today, with weekend fallback.

    Returns dict keyed by stock code: { code: {code, name, foreign, trust, prop, total3} }
    All values in 張 (lots). Negative = net sell.
    """
    if not date_yyyymmdd:
        d = datetime.now()
        while d.weekday() >= 5:  # back off to last weekday
            d = d - timedelta(days=1)
        date_yyyymmdd = d.strftime("%Y%m%d")

    url = URL_TEMPLATE.format(date=date_yyyymmdd)
    log(f"[t86] fetching {url}")
    raw = http_get_json(url, timeout=30)

    if raw.get("stat") and raw["stat"] != "OK":
        log(f"[t86] stat={raw.get('stat')} — no data for {date_yyyymmdd}")
        return {}

    rows = raw.get("data", []) or []
    result = {}
    for row in rows:
        if not row or len(row) <= IDX_TOTAL3_NET:
            continue
        code = str(row[IDX_CODE]).strip()
        if not code:
            continue
        result[code] = {
            "code": code,
            "name": str(row[IDX_NAME]).strip(),
            "foreign": _shares_to_lots(parse_int_safe(row[IDX_FOREIGN_NET])),
            "trust":   _shares_to_lots(parse_int_safe(row[IDX_TRUST_NET])),
            "prop":    _shares_to_lots(parse_int_safe(row[IDX_PROP_NET])),
            "total3":  _shares_to_lots(parse_int_safe(row[IDX_TOTAL3_NET])),
        }
    log(f"[t86] parsed {len(result)} stocks for {date_yyyymmdd}")
    return result


def top_n_by_field(t86_result, field, n=20, descending=True):
    """Sort all stocks by field, return top N. field ∈ {foreign, trust, prop, total3}."""
    items = list(t86_result.values())
    items.sort(key=lambda r: r.get(field, 0), reverse=descending)
    return items[:n]


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        result = fetch(date)
        # Top 10 by foreign net buy for verification
        top_foreign = top_n_by_field(result, "foreign", n=10)
        top_total3 = top_n_by_field(result, "total3", n=10)
        print(json.dumps({
            "count": len(result),
            "topForeign": top_foreign,
            "topTotal3": top_total3,
        }, ensure_ascii=False, indent=2))
    except Exception as e:
        log(f"[t86] FAILED: {e}")
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
