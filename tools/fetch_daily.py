"""Daily data orchestrator for SCD Engine.

Usage:
  python3 tools/fetch_daily.py           — full fetch, writes data/today.json
  python3 tools/fetch_daily.py --dry-run — print plan only, no writes

Calls: fubon → twse → tdcc → writes data/today.json
Progress is emitted as JSON lines to stdout for the HTTP server to stream.
"""

import json
import sys
import os
import time
from datetime import datetime

# Locate root + tools
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TOOLS_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")
sys.path.insert(0, TOOLS_DIR)

# 記憶體相關保證群組 — always fetch branch data for these regardless of whether
# they appear in the day's rankings (mirrors TIER_A_ANCHORS). 華邦電 / 南亞科 / 力成.
# 2026-07-01: added 國巨 2327 / 中石化 1314 — both fell out of the top-40 分點
# fetch and went stale (國巨 mf=8836 repeated 6/18→6/30, inflating streak/spon).
# Anchoring keeps their branch data fresh so golden isn't fed duplicate days.
MEMORY_ANCHORS = ["2344", "2408", "6239", "2327", "1314"]


def _prior_priority_from_snapshot(reports_dir, top_net=12):
    """Read the latest committed snapshot to seed the branch-fetch priority.

    Returns (prior_golden, prior_high_net):
      prior_golden   — tickers in rankings.golden (empty in P3a; auto-populates
                       when P3b scoring activates, so this hook needs no change).
      prior_high_net — tickers with the largest |weakening.net_cumulative|
                       (累積買超多 = persistent main-force flow worth tracking).
    Pure read; returns ([], []) if no snapshot is available.
    """
    import glob, re
    try:
        files = [f for f in glob.glob(os.path.join(reports_dir, "*.json"))
                 if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", os.path.basename(f))]
        if not files:
            return [], []
        latest = max(files)
        snap = json.loads(open(latest, encoding="utf-8").read())
    except Exception:
        return [], []

    def _as_ticker(x):
        if isinstance(x, dict):
            return x.get("ticker") or x.get("code")
        return x

    golden = [t for t in (_as_ticker(g) for g in snap.get("rankings", {}).get("golden", [])) if t]

    stocks = snap.get("stocks", [])
    def _net(s):
        return abs((s.get("weakening") or {}).get("net_cumulative") or 0)
    high_net = [s["ticker"] for s in sorted(stocks, key=_net, reverse=True)
                if s.get("ticker") and _net(s) > 0][:top_net]
    return golden, high_net


def build_branch_fetch_list(*, memory, tier_a, prior_golden, prior_high_net,
                            cross, fii_top, mf_top, fii_sell_top, mf_sell_top,
                            cap=40):
    """Deterministic priority order for the capped daily branch-fetch list.

    Priority (first wins, so the names we actually act on survive the cap):
      記憶體 anchors → Tier-A anchors → 昨日黃金名單 → 昨日高累積買超 →
      今日共現榜 → 今日外資/主力買超 → 今日外資/主力賣超.
    """
    ordered = (list(memory) + list(tier_a) + list(prior_golden) + list(prior_high_net)
               + list(cross) + list(fii_top) + list(mf_top)
               + list(fii_sell_top) + list(mf_sell_top))
    return list(dict.fromkeys(ordered))[:cap]


def emit(step, total, label, status="running", detail=""):
    """Emit a JSON progress line to stdout."""
    msg = {"step": step, "total": total, "label": label, "status": status, "detail": detail,
           "ts": datetime.now().strftime("%H:%M:%S")}
    print(json.dumps(msg, ensure_ascii=False), flush=True)


def safe_fetch(name, fn, *args, **kwargs):
    """Run fn(*args) with error isolation. Returns (result, error_str)."""
    try:
        result = fn(*args, **kwargs)
        return result, None
    except Exception as e:
        return None, str(e)


def derive_trading_date(twse_result):
    """Extract authoritative trading date.

    Logic:
    1. Get the date TWSE OpenAPI returned (often lags by ~1 day after close).
    2. If today is a weekday AND we are running after market close (≥15:00 local),
       and TWSE returned a date strictly older than today → use today as the
       trading date (Fubon real-time data is already for today).
    3. Otherwise use the TWSE-returned date (or last weekday as final fallback).
    """
    from datetime import timedelta
    twse_date = None
    try:
        td = twse_result.get("tradingDate") if twse_result else None
        if td and len(td) == 8 and td.isdigit():
            twse_date = f"{td[0:4]}-{td[4:6]}-{td[6:8]}"
    except Exception:
        pass

    now = datetime.now()
    today_is_weekday = now.weekday() < 5   # Mon–Fri
    after_close      = now.hour >= 15      # ≥ 15:00 台灣時間

    if today_is_weekday and after_close:
        today_str = now.strftime("%Y-%m-%d")
        if twse_date and twse_date < today_str:
            # TWSE T86 lags behind; Fubon real-time is already today → use today
            return today_str
        elif twse_date:
            return twse_date
        return today_str

    # Before close or weekend: trust TWSE date or fallback to last weekday
    if twse_date:
        return twse_date
    d = now
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def run(dry_run=False):
    TOTAL_STEPS = 10
    fetch_date = datetime.now().strftime("%Y-%m-%d")
    today_path = os.path.join(DATA_DIR, "today.json")

    emit(0, TOTAL_STEPS, "初始化...", status="running")

    if dry_run:
        emit(0, TOTAL_STEPS, "DRY RUN：不會寫入任何檔案", status="info")

    # ── Step 0.5 (logged as Step 1): Market Pulse — TAIEX + TX + 三大法人台指期 ─
    emit(1, TOTAL_STEPS, "抓取大盤脈搏 (TAIEX / 台指期 / 三大法人未平倉)...", status="running")
    try:
        from fetch_market_pulse import fetch_and_write as pulse_fetch
        import pathlib as _pl
        pulse_result = pulse_fetch(
            dry_run=dry_run,
            date_str=fetch_date,
            out_path=None if not dry_run else _pl.Path(DATA_DIR) / "market_pulse.json",
        )
        pulse_errors = pulse_result.get("errors", [])
        if pulse_errors:
            emit(1, TOTAL_STEPS, f"大盤脈搏部分失敗: {'; '.join(pulse_errors)}", status="warn")
        else:
            taiex_close = pulse_result.get("taiex", {}).get("close")
            emit(1, TOTAL_STEPS,
                 f"大盤脈搏完成  TAIEX={taiex_close}",
                 status="done")
    except Exception as e:
        emit(1, TOTAL_STEPS, f"大盤脈搏失敗 (非阻斷): {e}", status="warn")

    # ── Step 2: Fubon ZGK_D (外資買賣超排名) ──────────────────────────────────
    emit(2, TOTAL_STEPS, "抓取富邦外資買賣超排名 (ZGK_D)...", status="running")
    from fetch_fubon import fetch as fubon_fetch
    fubon_result, fubon_err = safe_fetch("fubon", fubon_fetch)
    if fubon_err:
        emit(2, TOTAL_STEPS, f"富邦 ZGK_D 失敗: {fubon_err}", status="warn", detail=fubon_err)
        buy_list = []
        sell_list = []
    else:
        buy_list = fubon_result.get("topBuy", [])
        sell_list = fubon_result.get("topSell", [])
        emit(2, TOTAL_STEPS, f"富邦外資買超 {len(buy_list)} 支，賣超 {len(sell_list)} 支",
             status="done", detail=f"top: {buy_list[0]['code'] if buy_list else '-'}")

    # ── Step 3: Fubon ZGK_F (主力買賣超排名) ──────────────────────────────────
    emit(3, TOTAL_STEPS, "抓取富邦主力買賣超排名 (ZGK_F)...", status="running")
    from fetch_fubon import fetch_institutional
    inst_result, inst_err = safe_fetch("fubon_inst", fetch_institutional)
    if inst_err:
        emit(3, TOTAL_STEPS, f"富邦 ZGK_F 失敗: {inst_err}", status="warn", detail=inst_err)
        main_force_buy = []
        main_force_sell = []
    else:
        main_force_buy = inst_result.get("topBuy", [])
        main_force_sell = inst_result.get("topSell", [])
        emit(3, TOTAL_STEPS, f"主力買超 {len(main_force_buy)} 支，賣超 {len(main_force_sell)} 支",
             status="done", detail=f"top: {main_force_buy[0]['code'] if main_force_buy else '-'}")

    # ── Step 4: TWSE OpenAPI (成交量前20 + 融資餘額) ────────────────────────────
    emit(4, TOTAL_STEPS, "抓取 TWSE 成交量 Top20 + 融資餘額...", status="running")
    from fetch_twse import fetch as twse_fetch
    twse_result, twse_err = safe_fetch("twse", twse_fetch)
    vol_top20 = []
    market_meta = {}
    if twse_err:
        emit(4, TOTAL_STEPS, f"TWSE 失敗: {twse_err}", status="warn", detail=twse_err)
    else:
        vol_top20 = twse_result.get("volTop20", [])
        market_meta = twse_result.get("marketMeta", {})
        emit(4, TOTAL_STEPS, f"TWSE 成交量 {len(vol_top20)} 支，融資 {market_meta.get('marginBalance',0):,} 張",
             status="done")

    # ── Step 5: TDCC 集保股權分散表 ────────────────────────────────────────────
    # Downloads the FULL market CSV from TDCC OpenData (id=1-5, ~2MB) and caches
    # it to data/tdcc/<YYYYMMDD>.json.  The pipeline (adapt_legacy) then reads
    # the cached file directly — no per-ticker filtering here.
    # fetch_and_save() is idempotent: if this week's file already exists it skips
    # the download entirely, so it's safe to call every trading day.
    emit(5, TOTAL_STEPS, "抓取 TDCC 集保股權分散表 (全市場 ~2MB，自動跳過已快取)...", status="running")
    stage3_prefill = {}  # kept for today.json backward compat (not consumed by pipeline)
    tdcc_err = None  # must exist before try — referenced at Step 10 sources list
    try:
        import pathlib as _pl
        import sys as _sys
        _ai_stock_root = _pl.Path(ROOT_DIR)
        if str(_ai_stock_root) not in _sys.path:
            _sys.path.insert(0, str(_ai_stock_root))
        from data.adapters import tdcc_adapter as _tdcc_mod
        _tdcc_dir = _ai_stock_root / "data" / "tdcc"
        if not dry_run:
            _out = _tdcc_mod.fetch_and_save(_tdcc_dir, force=False)
            emit(5, TOTAL_STEPS, f"TDCC 快取 → {_out.name}", status="done")
        else:
            emit(5, TOTAL_STEPS, "DRY RUN: TDCC 跳過 (不寫入)", status="skip")
    except Exception as _e:
        tdcc_err = str(_e)
        emit(5, TOTAL_STEPS, f"TDCC 失敗 (非阻斷): {_e}", status="warn", detail=str(_e))

    # ── Step 6: Cross-link & double-signal detection ───────────────────────────
    emit(6, TOTAL_STEPS, "比對外資 × 主力 × 成交量三榜...", status="running")
    buy_codes = {s["code"] for s in buy_list}
    mf_codes = {s["code"] for s in main_force_buy}

    vol_rows = []
    for v in vol_top20:
        row = dict(v)
        row["inBuyList"] = v["code"] in buy_codes
        row["inMainForce"] = v["code"] in mf_codes
        vol_rows.append(row)

    # Triple signal: appears in 外資 + 主力 + 成交量
    vol_codes = {v["code"] for v in vol_top20}
    triple = [c for c in buy_codes & mf_codes & vol_codes]
    double = [c for c in (buy_codes & mf_codes) - vol_codes]
    cross = triple + double  # priority order: triple first

    detail_codes = cross[:5]
    emit(6, TOTAL_STEPS,
         f"三榜共現 {len(triple)} 支，外資+主力雙榜 {len(double)} 支",
         status="done", detail=",".join(detail_codes))

    # ── Step 7: Sinotrade 分點資料 (top cross-signal + buy/sell-side tickers) ──
    emit(7, TOTAL_STEPS, "抓取分點資料 (三榜共現 + 外資/主力買超前10 + 外資/主力賣超前10)...", status="running")
    branches_dir = os.path.join(DATA_DIR, "branches")
    branch_fetch_summary = {"fetched": [], "failed": [], "skipped": []}
    # Cross-signal top 10 + FII/主力 top 10 (買超) + FII/主力 top 10 (賣超)
    # + Tier A regime anchors (always).
    # Tier A guarantees regime anchors get fresh branch data every day regardless
    # of whether they appear in cross-signal rankings.
    #
    # 賣超 tickers are included so Sinotrade's avgSellCost/sellBranches get
    # populated for sell-side names too — this feeds core/distribution.py's
    # 安全邊際 (current price vs main force cost) for tickers that only show
    # up in the sell-side rankings and would otherwise have no cost basis.
    TIER_A_ANCHORS = ["2330", "2317", "2382", "2454", "2308", "2881", "2882", "2891"]
    fii_top      = [s["code"] for s in buy_list[:10]]
    mf_top       = [s["code"] for s in main_force_buy[:10]]
    fii_sell_top = [s["code"] for s in sell_list[:10]]
    mf_sell_top  = [s["code"] for s in main_force_sell[:10]]
    # Priority: 記憶體/Tier-A anchors + 昨日黃金名單 + 昨日高累積買超 come FIRST so
    # the names we actually track survive the 40-cap; today's rankings fill the
    # rest. (prior golden is empty in P3a, auto-activates at P3b.)
    prior_golden, prior_high_net = _prior_priority_from_snapshot(
        os.path.join(ROOT_DIR, "reports"))
    sino_tickers = build_branch_fetch_list(
        memory=MEMORY_ANCHORS, tier_a=TIER_A_ANCHORS,
        prior_golden=prior_golden, prior_high_net=prior_high_net,
        cross=cross[:10], fii_top=fii_top, mf_top=mf_top,
        fii_sell_top=fii_sell_top, mf_sell_top=mf_sell_top, cap=40)

    if not sino_tickers:
        emit(7, TOTAL_STEPS, "無三榜/雙榜共現股，跳過分點抓取", status="skip")
    else:
        from fetch_sinotrade import fetch as sino_fetch
        if not dry_run:
            os.makedirs(branches_dir, exist_ok=True)
        for ticker in sino_tickers:
            sino_result, sino_err = safe_fetch(f"sino_{ticker}", sino_fetch, ticker)
            if sino_err or not sino_result:
                branch_fetch_summary["failed"].append({"ticker": ticker, "error": sino_err or "empty"})
            else:
                branch_fetch_summary["fetched"].append({
                    "ticker": ticker,
                    "buyBranches": len(sino_result.get("buyBranches", [])),
                    "avgBuyCost": sino_result.get("avgBuyCost"),
                })
                if not dry_run:
                    branch_path = os.path.join(branches_dir, f"{ticker}.json")
                    with open(branch_path, "w", encoding="utf-8") as bf:
                        json.dump(sino_result, bf, ensure_ascii=False, indent=2)
        ok = len(branch_fetch_summary["fetched"])
        fail = len(branch_fetch_summary["failed"])
        emit(7, TOTAL_STEPS,
             f"分點資料：{ok} 支成功、{fail} 支失敗",
             status="done" if fail == 0 else "warn",
             detail=",".join(b["ticker"] for b in branch_fetch_summary["fetched"][:5]))

    # ── Step 8: TWSE T86 三大法人 daily (authoritative full-market) ─────────────
    emit(8, TOTAL_STEPS, "抓取 TWSE T86 三大法人 daily (全市場)...", status="running")
    trading_date_yyyymmdd = None
    if not twse_err and twse_result.get("tradingDate"):
        td = twse_result["tradingDate"]
        if td and len(td) == 8 and td.isdigit():
            trading_date_yyyymmdd = td
    from fetch_twse_t86 import fetch as t86_fetch
    t86_result, t86_err = safe_fetch("twse_t86", t86_fetch, trading_date_yyyymmdd)
    if t86_err or not t86_result:
        emit(8, TOTAL_STEPS, f"T86 失敗: {t86_err or '空資料'}", status="warn", detail=t86_err or "")
        t86_result = {}
    else:
        emit(8, TOTAL_STEPS, f"T86 全市場 {len(t86_result)} 檔已取得", status="done")

    # ── Step 9: 多源交叉驗證 (Fubon vs T86 vs WantGoo for top 5) ───────────────
    emit(9, TOTAL_STEPS, "多源交叉驗證 (top 5 三榜共現)...", status="running")
    cross_verify = {"foreignOverlap": 0, "mainforceOverlap": 0, "perStock": {}}

    # Overlap of Fubon ZGK_D top 10 外資 vs T86 top 10 外資
    if buy_list and t86_result:
        fubon_top10 = [s["code"] for s in buy_list[:10]]
        t86_foreign_sorted = sorted(t86_result.values(), key=lambda r: r.get("foreign", 0), reverse=True)
        t86_top10_foreign = [r["code"] for r in t86_foreign_sorted[:10]]
        cross_verify["foreignOverlap"] = len(set(fubon_top10) & set(t86_top10_foreign))
        cross_verify["fubonForeignTop10"] = fubon_top10
        cross_verify["t86ForeignTop10"] = t86_top10_foreign

    # Overlap of Fubon ZGK_F top 5 主力 vs T86 top 5 三大法人
    if main_force_buy and t86_result:
        fubon_main_top5 = [s["code"] for s in main_force_buy[:5]]
        t86_total3_sorted = sorted(t86_result.values(), key=lambda r: r.get("total3", 0), reverse=True)
        t86_top5_total3 = [r["code"] for r in t86_total3_sorted[:5]]
        cross_verify["mainforceOverlap"] = len(set(fubon_main_top5) & set(t86_top5_total3))
        cross_verify["fubonMainTop5"] = fubon_main_top5
        cross_verify["t86Total3Top5"] = t86_top5_total3

    # Per-stock cross-verify (top 5 三榜共現)
    # WantGoo is opt-in (set ENABLE_WANTGOO=1) — Chrome headless currently hangs on the site
    enable_wantgoo = os.environ.get("ENABLE_WANTGOO") == "1"
    wantgoo_fetch = None
    if enable_wantgoo:
        from fetch_wantgoo import fetch as wantgoo_fetch
    for code in (triple[:5] if triple else cross[:5]):
        fubon_main_vol = next((s.get("buyVol", 0) for s in main_force_buy if s["code"] == code), 0)
        fubon_foreign_vol = next((s.get("buyVol", 0) for s in buy_list if s["code"] == code), 0)
        t86_row = t86_result.get(code, {})
        t86_foreign = t86_row.get("foreign", 0)
        t86_total3 = t86_row.get("total3", 0)

        # Try WantGoo (best-effort, may return None or be skipped)
        wg_data = None
        if wantgoo_fetch is not None:
            wg_data, _ = safe_fetch(f"wantgoo_{code}", wantgoo_fetch, code)

        entry = {
            "fubonMain": fubon_main_vol,
            "fubonForeign": fubon_foreign_vol,
            "t86Foreign": t86_foreign,
            "t86Total3": t86_total3,
        }
        # Compute delta% (foreign side, since both Fubon and T86 measure 外資 directly)
        if fubon_foreign_vol and t86_foreign:
            delta_pct = abs(fubon_foreign_vol - t86_foreign) / max(abs(fubon_foreign_vol), 1) * 100
            entry["foreignDeltaPct"] = round(delta_pct, 2)
            entry["foreignMatch"] = delta_pct < 1.0
        if wg_data:
            entry["wantgooMain"] = wg_data.get("mainForceBuyVol")
            entry["concentration5d"] = wg_data.get("concentration5d")
            entry["buyerSellerDiff"] = wg_data.get("buyerSellerDiff")
            if fubon_main_vol and wg_data.get("mainForceBuyVol"):
                wg_delta = abs(fubon_main_vol - wg_data["mainForceBuyVol"]) / max(abs(fubon_main_vol), 1) * 100
                entry["wantgooDeltaPct"] = round(wg_delta, 2)
                entry["wantgooMatch"] = wg_delta < 5.0
        cross_verify["perStock"][code] = entry

    matched_count = sum(1 for v in cross_verify["perStock"].values() if v.get("foreignMatch"))
    total_count = len(cross_verify["perStock"])
    emit(9, TOTAL_STEPS,
         f"多源驗證：外資榜重疊 {cross_verify['foreignOverlap']}/10、主力榜重疊 {cross_verify['mainforceOverlap']}/5、個股一致 {matched_count}/{total_count}",
         status="done")

    # ── Step 10: Write data/today.json ────────────────────────────────────────
    emit(10, TOTAL_STEPS, "寫入 data/today.json...", status="running")
    sources = []
    if not fubon_err:  sources.append("fubon-zgk-d")
    if not inst_err:   sources.append("fubon-zgk-f")
    if not twse_err:   sources.append("twse-mi20"); sources.append("twse-margn")
    if not tdcc_err:   sources.append("tdcc-od")
    if t86_result:     sources.append("twse-t86")
    if branch_fetch_summary.get("fetched"):  sources.append("sinotrade-branches")
    if any(v.get("wantgooMain") is not None for v in cross_verify["perStock"].values()):
        sources.append("wantgoo")

    # Resolve trading date from TWSE (authoritative) or fallback
    trading_date = derive_trading_date(twse_result if not twse_err else None)

    output = {
        "date": trading_date,          # 主要 date 欄 = 交易日 (e.g. 5/15 even when fetched on 5/17)
        "tradingDate": trading_date,   # 交易日（資料代表的日期）
        "fetchDate": fetch_date,       # 實際抓取日期
        "fetchedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources": sources,
        "buyList": buy_list,           # 外資買超
        "sellList": sell_list,         # 外資賣超
        "mainForceBuy": main_force_buy,  # 主力買超
        "mainForceSell": main_force_sell,  # 主力賣超
        "volRows": vol_rows,
        "openPrices": (twse_result.get("openPrices", {}) if not twse_err else {}),  # {code: 開盤價} 全市場, for backtest 次日開盤結算
        "marketMeta": market_meta,
        "stage3Prefill": stage3_prefill,
        "crossSignals": cross,         # 三榜 + 雙榜共現
        "tripleSignals": triple,       # 三榜全部共現（最強信號）
        "t86": t86_result,             # 全市場 三大法人 daily (TWSE 權威)
        "crossVerify": cross_verify,   # 多源驗證結果
        "branchData": branch_fetch_summary,  # 分點抓取摘要 (fetched/failed/skipped)
    }

    if not dry_run:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(today_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        branch_ok = len(branch_fetch_summary.get("fetched", []))
        emit(10, TOTAL_STEPS,
             f"完成！{trading_date} 收盤 · 外資 {len(buy_list)} 支 · 主力 {len(main_force_buy)} 支 · 三榜共現 {len(triple)} 支 · 分點 {branch_ok} 支",
             status="done", detail=today_path)
    else:
        emit(10, TOTAL_STEPS, "DRY RUN 完成，未寫檔", status="done")

    return output


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
