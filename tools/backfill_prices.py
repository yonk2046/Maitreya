"""tools/backfill_prices.py — 歷史重建快照的股價回填(SANDBOX 配套)

fetch_history 重建的快照籌碼欄位齊全,但 close=0/open=None(Fubon 榜的價格
無歷史來源)→ 回測進出場價全為 0。本工具用 TWSE STOCK_DAY(個股×月份日K,
含開/收盤)回填 data/backfill/snapshots/*.json 的:
    current_price(收盤) / open(開盤) / change_pct(真百分比) / change_amt(元)

特性:
  * 原始月檔快取到 data/backfill/history_prices/<ticker>_<yyyymm>.json,
    重跑自動跳過已抓的(中斷可續跑)。
  * 只打「快照中實際出現的 ticker × 月份」組合,請求數最小化。
  * 每次請求 sleep 2s(TWSE STOCK_DAY 有嚴格 rate limit,別調低)。
  * 只動 data/backfill/(沙盒),絕不碰 reports/ 或 data/snapshots/。

用法(在 Mac,需連 TWSE):
    python3 -m tools.backfill_prices              # 掃描+回填全部
    python3 -m tools.backfill_prices --dry-run    # 只列出要抓什麼
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _common import http_get_json, log  # noqa: E402

SNAPS_DIR = _AI_STOCK / "data" / "backfill" / "snapshots"
PRICES_DIR = _AI_STOCK / "data" / "backfill" / "history_prices"

STOCK_DAY_URL = ("https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
                 "?date={yyyymm}01&stockNo={ticker}&response=json")
SLEEP_SEC = 2.0


def _roc_to_iso(roc: str) -> str | None:
    """'115/03/02' → '2026-03-02'。"""
    try:
        y, m, d = roc.strip().split("/")
        return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return None


def _pf(v) -> float | None:
    """TWSE 字串數字('1,234.50'、'--'、'X0.00')→ float or None。"""
    try:
        s = str(v).replace(",", "").replace("X", "").strip()
        if s in ("", "--", "-"):
            return None
        return float(s)
    except Exception:
        return None


def _fetch_month(ticker: str, yyyymm: str, use_cache: bool = True,
                 cache_only: bool = False) -> dict[str, dict]:
    """回傳 {iso_date: {open, close, chg_amt}};月檔快取。cache_only=True 時
    不打網路(沙箱用),缺的月檔留給 Mac 跑補。"""
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    cache = PRICES_DIR / f"{ticker}_{yyyymm}.json"
    if use_cache and cache.is_file():
        raw = json.loads(cache.read_text(encoding="utf-8"))
    elif cache_only:
        return {}
    else:
        url = STOCK_DAY_URL.format(yyyymm=yyyymm, ticker=ticker)
        log(f"[prices] fetch {ticker} {yyyymm} ...")
        raw = http_get_json(url, timeout=30)
        cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        time.sleep(SLEEP_SEC)

    out: dict[str, dict] = {}
    if raw.get("stat") != "OK":
        return out
    # fields: 日期,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數
    for row in raw.get("data") or []:
        if len(row) < 8:
            continue
        iso = _roc_to_iso(row[0])
        if not iso:
            continue
        out[iso] = {
            "open":    _pf(row[3]),
            "close":   _pf(row[6]),
            "chg_amt": _pf(row[7]),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="backfill 快照股價回填")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache-only", action="store_true",
                    help="只用已快取的月檔回填,不打網路(沙箱環境用)")
    args = ap.parse_args()

    snap_files = sorted(SNAPS_DIR.glob("*.json"))
    if not snap_files:
        log("[prices] ❌ data/backfill/snapshots/ 是空的 — 先跑 backfill_range")
        return 1

    # ── 1. 掃描:需要哪些 ticker × 月份 ─────────────────────────────────────
    need: set[tuple[str, str]] = set()
    for f in snap_files:
        date = f.stem                      # 2026-03-02
        yyyymm = date[:4] + date[5:7]
        snap = json.loads(f.read_text(encoding="utf-8"))
        for stk in snap.get("stocks", []):
            t = str(stk.get("ticker") or "")
            # 只回填 4 碼普通股(排除權證 02001R、特別股等 — 回測不會交易它們)
            if len(t) == 4 and t.isdigit():
                need.add((t, yyyymm))

    todo = [(t, m) for (t, m) in sorted(need)
            if not (PRICES_DIR / f"{t}_{m}.json").is_file()]
    log(f"[prices] 快照 {len(snap_files)} 天,需要 {len(need)} 個 ticker×月份,"
        f"待抓 {len(todo)} 個(其餘已快取)")
    if args.dry_run:
        for t, m in todo[:20]:
            log(f"  would fetch {t} {m}")
        return 0

    # ── 2. 抓月檔(有快取自動跳過)────────────────────────────────────────
    fetched, failed = 0, 0
    price_map: dict[tuple[str, str], dict[str, dict]] = {}
    for i, (t, m) in enumerate(sorted(need), 1):
        try:
            price_map[(t, m)] = _fetch_month(t, m, cache_only=args.cache_only)
            fetched += 1
        except Exception as e:
            log(f"[prices] ⚠ {t} {m} 失敗: {e}")
            price_map[(t, m)] = {}
            failed += 1
        if i % 25 == 0:
            log(f"[prices] 進度 {i}/{len(need)}")

    # ── 3. 回填快照 ─────────────────────────────────────────────────────────
    patched_days, patched_stocks = 0, 0
    for f in snap_files:
        date = f.stem
        yyyymm = date[:4] + date[5:7]
        snap = json.loads(f.read_text(encoding="utf-8"))
        changed = False
        for stk in snap.get("stocks", []):
            t = stk.get("ticker")
            day = price_map.get((t, yyyymm), {}).get(date)
            if not day or not day.get("close"):
                continue
            close, opn, chg = day["close"], day.get("open"), day.get("chg_amt")
            stk["current_price"] = close
            stk["open"] = opn
            stk["change_amt"] = chg
            prev = (close - chg) if (chg is not None) else None
            stk["change_pct"] = round(chg / prev * 100, 2) if (chg is not None and prev) else stk.get("change_pct")
            changed = True
            patched_stocks += 1
        if changed:
            snap.setdefault("_price_backfill", "twse_stock_day")
            f.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            patched_days += 1

    log(f"[prices] ✅ 完成:回填 {patched_days} 天 / {patched_stocks} 筆股價"
        f"(月檔 {fetched} 個,失敗 {failed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
