"""補抓歷史日期資料（當日忘記掃描時使用）。

Usage:
  python3 tools/fetch_history.py 2026-05-19

資料來源：
  ✓ TWSE T86    — 三大法人(外資/投信/自營)，支援指定日期
  ✓ TDCC        — 股東人數（週資料，用最近一次）
  ✗ Fubon ZGK_D — 外資排名，只有即時，無歷史
  ✗ Fubon ZGK_F — 主力排名，只有即時，無歷史

輸出：data/history/YYYY-MM-DD.json（格式與 today.json 相容）
"""

import json, sys, os
from datetime import datetime, timedelta

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR  = os.path.dirname(TOOLS_DIR)
DATA_DIR  = os.path.join(ROOT_DIR, "data")
sys.path.insert(0, TOOLS_DIR)

from _common import log
from fetch_twse_t86 import fetch as t86_fetch
from fetch_tdcc import fetch as tdcc_fetch


def emit(label, status="running", detail=""):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"running": "⏳", "done": "✓", "warn": "⚠", "info": "ℹ"}.get(status, "·")
    print(f"  {icon} {label}" + (f" — {detail}" if detail else ""), flush=True)


def parse_target_date(arg):
    """Accept 2026-05-19 or 20260519."""
    arg = arg.strip().replace("-", "")
    if len(arg) != 8 or not arg.isdigit():
        raise ValueError(f"Invalid date: {arg}. Use YYYY-MM-DD or YYYYMMDD.")
    yyyy, mm, dd = arg[:4], arg[4:6], arg[6:]
    return f"{yyyy}-{mm}-{dd}", arg  # (iso, yyyymmdd)


def last_weekday(iso_date):
    """Return the last weekday on or before iso_date."""
    d = datetime.strptime(iso_date, "%Y-%m-%d")
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d"), d.strftime("%Y%m%d")


def run(target_iso):
    target_iso, target_yyyymmdd = parse_target_date(target_iso)
    # Verify it's actually a weekday
    _, actual_yyyymmdd = last_weekday(target_iso)
    if actual_yyyymmdd != target_yyyymmdd:
        emit(f"{target_iso} 是假日，將使用前一交易日 {actual_yyyymmdd[:4]}-{actual_yyyymmdd[4:6]}-{actual_yyyymmdd[6:]}", "warn")
        target_iso = f"{actual_yyyymmdd[:4]}-{actual_yyyymmdd[4:6]}-{actual_yyyymmdd[6:]}"
        target_yyyymmdd = actual_yyyymmdd

    print(f"\n🔍 補抓 {target_iso} 歷史資料\n")

    # ── Step 1: TWSE T86 ──────────────────────────────────────────────────────
    emit(f"TWSE T86 三大法人 ({target_iso})...", "running")
    try:
        t86 = t86_fetch(target_yyyymmdd)
        if not t86:
            emit("T86 無資料（可能為假日或資料未公開）", "warn")
            t86 = {}
        else:
            emit(f"T86 取得 {len(t86)} 支", "done")
    except Exception as e:
        emit(f"T86 失敗: {e}", "warn")
        t86 = {}

    # ── Step 2: 從 T86 建立 buyList 替代（外資淨買超 top 8，排除 ETF）────────
    def is_etf(code): return str(code).startswith("00")
    foreign_top = sorted(
        [r for r in t86.values() if not is_etf(r["code"]) and r.get("foreign", 0) > 0],
        key=lambda r: r["foreign"], reverse=True
    )[:8]
    buy_list = [
        {"rank": i+1, "code": r["code"], "name": r["name"],
         "buyVol": r["foreign"], "close": 0, "chgPct": 0, "isETF": False,
         "source": "t86"}
        for i, r in enumerate(foreign_top)
    ]
    emit(f"從 T86 建立外資替代 buyList: {[r['code'] for r in buy_list]}", "done")

    # ── Step 3: 主力 (自營商 dealer) top from T86 ─────────────────────────────
    dealer_top = sorted(
        [r for r in t86.values() if not is_etf(r["code"]) and r.get("prop", 0) > 0],
        key=lambda r: r["prop"], reverse=True
    )[:20]
    main_force_buy = [
        {"rank": i+1, "code": r["code"], "name": r["name"],
         "buyVol": r["prop"], "close": 0, "chgPct": 0, "isETF": False,
         "source": "t86-dealer"}
        for i, r in enumerate(dealer_top)
    ]
    emit(f"從 T86 自營商建立 mainForceBuy 替代: {len(main_force_buy)} 支", "done")

    # ── Step 4: TDCC 股東人數（同週資料）────────────────────────────────────
    all_codes = list({r["code"] for r in buy_list + main_force_buy})
    emit(f"TDCC 股東人數（共 {len(all_codes)} 支）...", "running")
    try:
        tdcc = tdcc_fetch(all_codes) or {}
        stage3_prefill = {
            code: {"holderNow": d.get("totalHolders", 0), "bigHolderPct": d.get("bigHolderPct", 0)}
            for code, d in tdcc.items()
        }
        emit(f"TDCC 取得 {len(stage3_prefill)} 支", "done")
    except Exception as e:
        emit(f"TDCC 失敗: {e}", "warn")
        stage3_prefill = {}

    # ── Step 5: Cross signals ─────────────────────────────────────────────────
    buy_codes = {r["code"] for r in buy_list}
    mf_codes  = {r["code"] for r in main_force_buy}
    cross     = list(buy_codes & mf_codes)
    emit(f"外資×主力共現: {cross}", "done" if cross else "info")

    # ── Step 6: Write output ──────────────────────────────────────────────────
    out_dir = os.path.join(DATA_DIR, "history")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{target_iso}.json")

    output = {
        "date":          target_iso,
        "tradingDate":   target_iso,
        "fetchDate":     datetime.now().strftime("%Y-%m-%d"),
        "fetchedAt":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "isHistorical":  True,
        "sources":       ["twse-t86"] + (["tdcc-od"] if stage3_prefill else []),
        "note":          "Fubon ZGK_D/ZGK_F 無歷史資料；buyList 和 mainForceBuy 由 T86 外資/自營商重建",
        "buyList":       buy_list,
        "sellList":      [],
        "mainForceBuy":  main_force_buy,
        "mainForceSell": [],
        "volRows":       [],
        "marketMeta":    {},
        "stage3Prefill": stage3_prefill,
        "crossSignals":  cross,
        "tripleSignals": [],
        "t86":           t86,
        "crossVerify":   {},
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成！儲存至 data/history/{target_iso}.json")
    print(f"   外資 Top: {[r['code'] for r in buy_list]}")
    print(f"   共現:     {cross}")
    print(f"\n⚠️  注意：Fubon 主力排名無歷史資料，mainForceBuy 以 T86 自營商替代，僅供參考。")
    print(f"   完整分析請在 SCD Engine 載入此檔案（loadHistoryData）。\n")
    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_history.py 2026-05-19")
        sys.exit(1)
    try:
        run(sys.argv[1])
    except Exception as e:
        print(f"❌ 失敗: {e}")
        sys.exit(1)
