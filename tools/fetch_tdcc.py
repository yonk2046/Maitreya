"""Fetch TDCC stockholder distribution data for a list of stock codes.

Source: TDCC opendata id=1-5 — full market weekly distribution (UTF-8 CSV, ~2.2MB).
Returns per-stock: totalHolders, bigHolderPct (tier 13+: 600K+ shares = ~600 lots)
"""

import json
import sys
import csv
import io
import urllib.request
from _common import log, parse_int_safe, parse_float_safe

TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5&key=anonymous"
BIG_HOLDER_TIER = 13  # tier ≥ 13 → 600,001+ shares (≈600 lots), considered institutional/big player


def fetch(target_codes=None):
    """
    Download TDCC distribution CSV and compute per-stock stockholder stats.
    target_codes: list of stock codes to extract (None = all, slow)
    Returns { code: { date, totalHolders, bigHolderPct } }
    """
    log("[tdcc] downloading stockholder distribution (~2.2MB)...")
    req = urllib.request.Request(TDCC_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read()
    html = raw.decode("utf-8-sig", errors="replace")
    log(f"[tdcc] downloaded {len(raw)//1024} KB")

    target_set = set(c.strip() for c in target_codes) if target_codes else None

    # Aggregate by stock code
    totals = {}   # code → { date, holders, bigHolders, totalShares, bigShares }
    reader = csv.DictReader(io.StringIO(html))
    for row in reader:
        code = row.get("證券代號", "").strip()
        if not code:
            continue
        if target_set and code not in target_set:
            continue
        date = row.get("資料日期", "").strip()
        tier = parse_int_safe(row.get("持股分級", 0))
        holders = parse_int_safe(row.get("人數", 0))
        pct = parse_float_safe(row.get("占集保庫存數比例%", 0))

        if code not in totals:
            totals[code] = {"date": date, "totalHolders": 0, "bigHolders": 0, "bigSharePct": 0.0}

        if tier == 17:
            # tier 17 is the aggregate total row — use its 人數 as definitive total holder count
            totals[code]["totalHolders"] = holders
        elif BIG_HOLDER_TIER <= tier <= 16:
            # tiers 13-16: 600K+ shares = large institutional/whale players
            totals[code]["bigHolders"] += holders
            totals[code]["bigSharePct"] = round(totals[code]["bigSharePct"] + pct, 2)

    result = {}
    for code, d in totals.items():
        result[code] = {
            "date": d["date"],
            "totalHolders": d["totalHolders"],
            "bigHolderCount": d["bigHolders"],
            "bigHolderPct": round(d["bigSharePct"], 2),
        }

    log(f"[tdcc] extracted {len(result)} stocks")
    return result


if __name__ == "__main__":
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["3481", "2344", "2317", "6770"]
    try:
        result = fetch(target_codes=codes)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        log(f"[tdcc] FAILED: {e}")
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
