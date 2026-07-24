"""tools/fetch_ohlc.py — TWSE 個股日成交資訊(STOCK_DAY)OHLC 回填 → data/ohlc/<ticker>.json

Wave C2 (2026-07-24/25), fable 裁定 R3:「Schema 2.0 = 一次性事件,現在只集不動。」
本工具只把開/高/低/收原始資料備好放 data/ohlc/,**不接進 ingest / 快照 / core /
schema**。OHLC 併入快照(真 ATR、次日開盤結算精確化)是 Schema 2.0 的事,見
docs/migration/EXEC-PLAN-backtest-arc-20260723.md R3 與清單 4.4。

Source: TWSE 個股日成交資訊 STOCK_DAY(公開合法免費,無需授權)——
    https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=YYYYMM01&stockNo=TICKER&response=json
逐股逐月端點:一次呼叫回傳該股「整個月」的日 K(開/高/低/收/量),呼叫量隨
「股數 × 月數」線性成長,對此端點的嚴格 rate limit 務必節流(每次網路請求
sleep ≥2s,不得調低,對齊 tools/backfill_prices.py 既有紀律)。

Resumable(斷點續抓): 每個 (ticker, yyyymm) 的原始回應快取到
    data/ohlc/.raw_cache/<ticker>_<yyyymm>.json
重跑時只要快取檔已存在就直接讀檔,完全跳過網路呼叫與 sleep——中斷後重跑
同一指令即可從中斷處續抓。合併後的每股輸出寫到 data/ohlc/<ticker>.json,
且是「併入」而非覆蓋:既有 days 與新抓的 days 做 dict 合併,不同批次、不同
--from/--to 的重跑不會互相清掉對方抓到的日期。

Universe(未給 --tickers 時): reports/YYYY-MM-DD.json(WORM 快照,排除
.intelligence/.sha256/.example 變體)中 date >= --from 的所有日期,取
stocks[].ticker 聯集,只留 4 碼純數字普通股(同 tools/backfill_prices.py 既有
紀律,排除權證與少數 ticker 混碼異常,例如已知的 3673TPK/6456GIS 上游資料
瑕疵),再聯集 core.engine_params.TIER_A 錨定名單。

輸出 schema(data/ohlc/<ticker>.json):
{
  "ticker": "2330",
  "source": "twse-STOCK_DAY",
  "generated_at": "2026-07-25T09:00:00+08:00",
  "days": {
    "2026-07-01": {"open": 838.0, "high": 845.0, "low": 835.0, "close": 840.0,
                   "volume": 12345678, "source": "twse-STOCK_DAY"},
    ...
  }
}
缺日(假日/停牌/當日未上市/未成交)= 該日期鍵不存在——不補 0、不外插、不假造
(as-was 原則,C10)。`volume` 單位為股數(TWSE 原始「成交股數」,未除以 1000)。

CLI:
    python3 tools/fetch_ohlc.py --dry-run                      # 只列出將抓取的 ticker×月份組合,不打網路
    python3 tools/fetch_ohlc.py --tickers 2330,2317,2002 --from 2026-07-01 --to 2026-07-24
    python3 tools/fetch_ohlc.py --from 2026-05-08 --to 2026-07-24   # 全宇宙全期間回填(長時間任務,見下方提醒)

⚠ 全宇宙全期間回填耗時長(股數 × 月數 次請求,每次 ≥2s 節流),建議 nohup/
detached 執行,不要在互動式 600s watchdog 的 session 裡一次跑完整範圍。
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
from typing import Any, Callable

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

TW_TZ = timezone(timedelta(hours=8))

REPORTS_DIR = _AI_STOCK / "reports"
OHLC_DIR = _AI_STOCK / "data" / "ohlc"
RAW_CACHE_DIR = OHLC_DIR / ".raw_cache"

STOCK_DAY_URL = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    "?date={yyyymm}01&stockNo={ticker}&response=json"
)
SOURCE_TAG = "twse-STOCK_DAY"

BACKFILL_START = "2026-05-08"   # R3/清單 4.4:對齊回測弧快照起點
MIN_SLEEP_SEC = 2.0             # TWSE STOCK_DAY 嚴格 rate limit,不得調低

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.twse.com.tw/",
}

_REPORT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TICKER_RE = re.compile(r"^\d{4}$")


# ── HTTP (isolated so tests can monkeypatch the single symbol) ──────────────

def _get_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8-sig"))


# ── Pure parsing helpers ─────────────────────────────────────────────────────

def _roc_to_iso(roc_date: str) -> str | None:
    """'115/07/08'(民國年)→ '2026-07-08'。格式不符回傳 None。"""
    parts = str(roc_date).strip().split("/")
    if len(parts) != 3:
        return None
    try:
        y = int(parts[0]) + 1911
        m = int(parts[1])
        d = int(parts[2])
    except ValueError:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def _num(v: Any) -> float | None:
    """TWSE 數字字串('1,234.50'、'--'、'X0.00')→ float,不可解析回傳 None。"""
    s = str(v).replace(",", "").replace("X", "").replace("+", "").strip()
    if s in ("", "--", "-", "－"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_stock_day(raw: dict) -> dict[str, dict[str, Any]]:
    """純函數:TWSE STOCK_DAY 原始回應 → {iso_date: {open,high,low,close,volume}}。

    TWSE STOCK_DAY 欄位順序(fields 一致,不逐檔查也可靠):
      0 日期(民國) 1 成交股數 2 成交金額 3 開盤價 4 最高價 5 最低價
      6 收盤價 7 漲跌價差 8 成交筆數
    stat != "OK"(例如該股當月無交易資料)回傳空 dict——不是錯誤,是「這個月
    這檔股票沒有資料」的誠實表達(可能停牌/未上市/下市)。
    """
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict) or raw.get("stat") != "OK":
        return out
    for row in raw.get("data") or []:
        if len(row) < 7:
            continue
        iso = _roc_to_iso(row[0])
        if iso is None:
            continue
        close = _num(row[6])
        if close is None:
            continue
        out[iso] = {
            "open":   _num(row[3]),
            "high":   _num(row[4]),
            "low":    _num(row[5]),
            "close":  close,
            "volume": int(_num(row[1])) if _num(row[1]) is not None else None,
            "source": SOURCE_TAG,
        }
    return out


def month_list(date_from: str, date_to: str) -> list[str]:
    """['2026-05-08', '2026-07-24'] → ['202605','202606','202607'](含頭尾月)。"""
    y0, m0 = int(date_from[:4]), int(date_from[5:7])
    y1, m1 = int(date_to[:4]), int(date_to[5:7])
    if (y1, m1) < (y0, m0):
        return []
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


# ── Universe discovery ───────────────────────────────────────────────────────

def discover_universe(
    reports_dir: pathlib.Path = REPORTS_DIR,
    since_date: str = BACKFILL_START,
    *,
    include_tier_a: bool = True,
) -> set[str]:
    """reports/YYYY-MM-DD.json(WORM 快照,date>=since_date)裡出現過的 ticker
    聯集,再聯集 TIER_A。只留 4 碼純數字普通股(排除權證/混碼異常 ticker,同
    tools/backfill_prices.py 既有紀律)。reports_dir 不存在時回傳空集合(供
    測試以假目錄呼叫)。
    """
    tickers: set[str] = set()
    if reports_dir.is_dir():
        for f in sorted(reports_dir.glob("20*.json")):
            if not _REPORT_DATE_RE.match(f.stem):
                continue
            if f.stem < since_date:
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for stk in d.get("stocks", []) or []:
                t = str(stk.get("ticker") or "")
                if _TICKER_RE.match(t):
                    tickers.add(t)

    if include_tier_a:
        try:
            from core.engine_params import TIER_A
            tickers.update(TIER_A.keys())
        except ImportError:
            pass

    return tickers


# ── Fetch (cached, resumable) ────────────────────────────────────────────────

def fetch_month_raw(
    ticker: str,
    yyyymm: str,
    *,
    raw_cache_dir: pathlib.Path = RAW_CACHE_DIR,
    sleep_s: float = MIN_SLEEP_SEC,
    get_json_fn: Callable[[str], Any] = _get_json,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    """單一 ticker×月份的 TWSE STOCK_DAY 原始回應,快取到 raw_cache_dir。

    快取命中 → 直接讀檔回傳,不打網路、不 sleep(這是「已存在的檔跳過」的
    斷點續抓語意)。快取未命中 → 打網路、寫快取、sleep(節流下限強制 ≥2s,
    無論呼叫端傳入什麼都不會低於 MIN_SLEEP_SEC)。
    """
    raw_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_cache_dir / f"{ticker}_{yyyymm}.json"
    if cache_path.is_file():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    url = STOCK_DAY_URL.format(yyyymm=yyyymm, ticker=ticker)
    raw = get_json_fn(url)
    cache_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    sleep_fn(max(sleep_s, MIN_SLEEP_SEC))
    return raw


def build_ticker_days(
    ticker: str,
    months: list[str],
    *,
    raw_cache_dir: pathlib.Path = RAW_CACHE_DIR,
    sleep_s: float = MIN_SLEEP_SEC,
    get_json_fn: Callable[[str], Any] = _get_json,
    sleep_fn: Callable[[float], None] = time.sleep,
    log_fn: Callable[[str], None] = lambda s: None,
) -> dict[str, dict]:
    """單一 ticker 跨多個月份抓取 + 合併 → {iso_date: {...}}。任何單月失敗
    (網路例外)不中斷整體:記一筆 log,該月留空,其餘月份照常進行——一檔股票
    某個月抓不到,不該讓整輪回填全部失敗。
    """
    days: dict[str, dict] = {}
    for yyyymm in months:
        try:
            raw = fetch_month_raw(
                ticker, yyyymm,
                raw_cache_dir=raw_cache_dir, sleep_s=sleep_s,
                get_json_fn=get_json_fn, sleep_fn=sleep_fn,
            )
        except Exception as e:  # noqa: BLE001 — 節流迴圈裡單月失敗不可讓整檔股票停擺
            log_fn(f"  ⚠ {ticker} {yyyymm} 失敗: {e}")
            continue
        days.update(parse_stock_day(raw))
    return days


def write_ticker_file(
    ticker: str,
    days: dict[str, dict],
    *,
    out_dir: pathlib.Path = OHLC_DIR,
) -> pathlib.Path:
    """寫 data/ohlc/<ticker>.json——與既有檔案的 days 做 dict 合併(新資料
    覆蓋同日鍵,不同批次不會互相清掉對方抓到的日期),不是整檔覆蓋。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{ticker}.json"
    merged_days: dict[str, dict] = {}
    if out_path.is_file():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            merged_days.update(existing.get("days") or {})
        except (OSError, json.JSONDecodeError):
            pass
    merged_days.update(days)

    payload = {
        "ticker": ticker,
        "source": SOURCE_TAG,
        "generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"),
        "days": dict(sorted(merged_days.items())),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


# ── CLI orchestration ────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _rel(path: pathlib.Path) -> str:
    """Best-effort project-relative display path; falls back to the absolute
    path when path isn't under the project root (e.g. a tmp_path in tests)."""
    try:
        return str(path.relative_to(_AI_STOCK))
    except ValueError:
        return str(path)


def run(
    tickers: list[str],
    date_from: str,
    date_to: str,
    *,
    dry_run: bool = False,
    raw_cache_dir: pathlib.Path = RAW_CACHE_DIR,
    out_dir: pathlib.Path = OHLC_DIR,
    sleep_s: float = MIN_SLEEP_SEC,
    get_json_fn: Callable[[str], Any] = _get_json,
    sleep_fn: Callable[[float], None] = time.sleep,
    log_fn: Callable[[str], None] = _log,
) -> dict[str, int]:
    months = month_list(date_from, date_to)
    log_fn(f"[fetch_ohlc] {len(tickers)} 檔 × {len(months)} 個月 = {len(tickers) * len(months)} 個 ticker×月份組合"
           f"({date_from} → {date_to})")

    if dry_run:
        for t in tickers[:20]:
            log_fn(f"  would fetch {t}: {months}")
        if len(tickers) > 20:
            log_fn(f"  … 以及另外 {len(tickers) - 20} 檔")
        return {"tickers": len(tickers), "months": len(months), "written": 0}

    written = 0
    total_days = 0
    for i, ticker in enumerate(sorted(tickers), 1):
        days = build_ticker_days(
            ticker, months,
            raw_cache_dir=raw_cache_dir, sleep_s=sleep_s,
            get_json_fn=get_json_fn, sleep_fn=sleep_fn, log_fn=log_fn,
        )
        out_path = write_ticker_file(ticker, days, out_dir=out_dir)
        written += 1
        total_days += len(days)
        log_fn(f"[fetch_ohlc] ({i}/{len(tickers)}) {ticker}: {len(days)} 天 → {_rel(out_path)}")

    log_fn(f"[fetch_ohlc] ✓ 完成:{written} 檔股票,合計 {total_days} 筆日 K 寫入 {_rel(out_dir)}/")
    return {"tickers": written, "months": len(months), "written": written, "days": total_days}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="TWSE 個股日成交資訊(STOCK_DAY)OHLC 回填 → data/ohlc/<ticker>.json"
    )
    ap.add_argument("--tickers", default=None,
                     help="逗號分隔 ticker 清單,例如 2330,2317,2002(未給則掃描 reports/ 既有宇宙 + TIER_A)")
    ap.add_argument("--from", dest="date_from", default=BACKFILL_START,
                     help=f"起始日 YYYY-MM-DD(預設 {BACKFILL_START},對齊回測弧快照起點)")
    ap.add_argument("--to", dest="date_to", default=None,
                     help="結束日 YYYY-MM-DD(預設今天,台北時區)")
    ap.add_argument("--dry-run", action="store_true", help="只列出將抓取的組合,不打網路、不寫檔")
    ap.add_argument("--sleep", type=float, default=MIN_SLEEP_SEC,
                     help=f"每次網路請求間隔秒數(下限強制 {MIN_SLEEP_SEC}s,傳更小的值不會生效)")
    args = ap.parse_args(argv)

    date_to = args.date_to or datetime.now(TW_TZ).strftime("%Y-%m-%d")

    if args.tickers:
        tickers = sorted({t.strip() for t in args.tickers.split(",") if t.strip()})
    else:
        tickers = sorted(discover_universe(since_date=args.date_from))

    if not tickers:
        _log("[fetch_ohlc] ❌ 空的 ticker 清單——reports/ 掃不到資料且未給 --tickers")
        return 1

    run(tickers, args.date_from, date_to, dry_run=args.dry_run, sleep_s=args.sleep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
