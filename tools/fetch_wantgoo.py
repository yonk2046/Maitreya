"""Best-effort per-stock fetch from WantGoo 主力進出動向.

Status (2026-05-19): WantGoo API endpoint /stock/<code>/major-investors/main-trend-data
returns 400 without fingerprint headers, and Chrome headless hangs on the page
(likely anti-bot detection). This fetcher returns None gracefully on failure so
the pipeline doesn't crash; the primary 多源驗證 path uses TWSE T86 instead.

If a workable approach is found later, plug it into _try_fetch() and the rest
of the pipeline keeps working without changes.
"""

import json
import sys
import re
from _common import http_get, chrome_render, parse_int_safe, parse_float_safe, log


URL_TEMPLATE = "https://www.wantgoo.com/stock/{code}/major-investors/main-trend"


def _try_chrome(code, timeout_seconds=30, virtual_time_budget_ms=6000):
    """Attempt Chrome render with short timeout. Returns parsed dict or None."""
    try:
        html = chrome_render(URL_TEMPLATE.format(code=code),
                             timeout_seconds=timeout_seconds,
                             virtual_time_budget_ms=virtual_time_budget_ms)
    except Exception as e:
        log(f"[wantgoo] {code} chrome failed: {e}")
        return None
    return _parse_html(html, code)


def _parse_html(html, code):
    """Best-effort parse of rendered WantGoo HTML for the first data row."""
    if not html or len(html) < 1000:
        return None
    # Strategy: find first <tr> in #main-trend tbody with data cells
    m = re.search(r'id=["\']?main-trend["\']?[^>]*>.*?<tbody[^>]*>(.*?)</tbody>',
                  html, re.DOTALL)
    if not m:
        return None
    tbody = m.group(1)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody, re.DOTALL)
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 6:
            continue
        # Expected order (from main-trend.min.js):
        # 0:date 1:close 2:主力買賣超 3:買賣家數差 4:5日集中度% 5:20日集中度%
        date_str = re.sub(r"<[^>]*>", "", cells[0]).strip()
        main_force = parse_int_safe(re.sub(r"<[^>]*>", "", cells[2]).strip())
        diff = parse_int_safe(re.sub(r"<[^>]*>", "", cells[3]).strip())
        skp5_raw = re.sub(r"<[^>]*>", "", cells[4]).strip().replace("%", "")
        skp20_raw = re.sub(r"<[^>]*>", "", cells[5]).strip().replace("%", "")
        return {
            "code": code,
            "mainForceBuyVol": main_force,
            "buyerSellerDiff": diff,
            "concentration5d": parse_float_safe(skp5_raw),
            "concentration20d": parse_float_safe(skp20_raw),
            "asOf": date_str,
            "source": "wantgoo-chrome",
        }
    return None


def fetch(code):
    """Fetch per-stock main-trend snapshot. Returns dict or None on failure."""
    log(f"[wantgoo] fetching {code}")
    return _try_chrome(code)


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "3481"
    result = fetch(code)
    if result is None:
        print(json.dumps({"error": "wantgoo unavailable", "code": code}))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
