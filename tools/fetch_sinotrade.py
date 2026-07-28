"""Fetch Sinotrade stockchannel 分點 (broker branch) data for a single stock.

URL: https://stockchannelnew.sinotrade.com.tw/z/zc/zco/zco_<ticker>.djhtm
BIG5 encoded. No auth required.
Output: JSON with buyBranches[], sellBranches[], avgBuyCost, avgSellCost, totalBuyVol, totalSellVol
"""

import datetime
import json
import sys
import re
from _common import http_get, extract_table_rows, parse_int_safe, parse_float_safe, log

BASE_URL = "https://stockchannelnew.sinotrade.com.tw/z/zc/zco/zco_{ticker}.djhtm"
PCT_PATTERN = re.compile(r"([\d.]+)%")


def fetch(ticker, session_date=None):
    ticker = str(ticker).strip()
    url = BASE_URL.format(ticker=ticker)
    log(f"[sinotrade] fetching branches for {ticker}...")
    raw = http_get(url, timeout=20)
    html = raw.decode("big5", errors="replace")
    rows = extract_table_rows(html, min_cells=4)

    buy_branches = []
    sell_branches = []
    total_buy_vol = 0
    total_sell_vol = 0
    avg_buy_cost = 0.0
    avg_sell_cost = 0.0

    for r in rows:
        if not r or not r[0].strip():
            continue
        # Skip header row
        if r[0] in ("買超券商", "合計買超張數", "平均買超成本"):
            if r[0] == "合計買超張數" and len(r) >= 4:
                total_buy_vol = parse_int_safe(r[1])
                total_sell_vol = parse_int_safe(r[3])
            elif r[0] == "平均買超成本" and len(r) >= 4:
                avg_buy_cost = parse_float_safe(r[1])
                avg_sell_cost = parse_float_safe(r[3])
            continue

        # Data row: [buy_broker, buy_in, buy_out, net_buy, buy_pct, sell_broker, ...]
        if len(r) >= 10:
            # Buy side
            b_name = r[0].strip()
            b_buy = parse_int_safe(r[1])
            b_sell = parse_int_safe(r[2])
            b_net = parse_int_safe(r[3])
            m = PCT_PATTERN.search(r[4])
            b_pct = float(m.group(1)) if m else 0.0
            if b_name:
                buy_branches.append({"broker": b_name, "buyVol": b_buy, "sellVol": b_sell,
                                      "netBuy": b_net, "pct": b_pct})
            # Sell side
            s_name = r[5].strip()
            s_buy = parse_int_safe(r[6])
            s_sell = parse_int_safe(r[7])
            s_net = parse_int_safe(r[8])
            m2 = PCT_PATTERN.search(r[9])
            s_pct = float(m2.group(1)) if m2 else 0.0
            if s_name:
                sell_branches.append({"broker": s_name, "buyVol": s_buy, "sellVol": s_sell,
                                       "netSell": s_net, "pct": s_pct})

    log(f"[sinotrade] {ticker}: buy={len(buy_branches)} branches, avgBuyCost={avg_buy_cost}")
    return {
        "ticker": ticker,
        # 資料所屬的「交易日」(YYYY-MM-DD)。修正案 C-2:分點資料是當日盤後
        # 產物,寫入此欄讓讀取端能逐檔判定新鮮度,不再拿舊交易日殘資料充今值。
        # 向後相容:舊 branch 檔無此欄,讀取端退回檔案 mtime 日期(見 legacy.py)。
        #
        # session_date 由呼叫端(fetch_daily)以 derive_trading_date 解出的權威交易日
        # 傳入。**不可退回執行當天的日曆日**:早班 T+1 補跑(08:35,盤前)抓到的是
        # 前一個 session 的分點,若記成執行日,legacy.py 的 `fd < target_date` 會把
        # 昨日殘值判為新鮮而放行 —— 正是 C-2 要擋的事(2026-07-28 查出)。
        # 只有獨立 CLI 執行(無呼叫端資訊)才退回今天。
        "fetched_date": session_date or datetime.date.today().isoformat(),
        "buyBranches": buy_branches,
        "sellBranches": sell_branches,
        "totalBuyVol": total_buy_vol,
        "totalSellVol": total_sell_vol,
        "avgBuyCost": avg_buy_cost,
        "avgSellCost": avg_sell_cost,
    }


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "3481"
    try:
        result = fetch(ticker)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        log(f"[sinotrade] FAILED: {e}")
        print(json.dumps({"error": str(e), "ticker": ticker, "buyBranches": [], "sellBranches": []}))
        sys.exit(1)
