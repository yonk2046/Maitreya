"""tools/fetch_taiex_history.py — backfill TAIEX daily close → data/taiex_history.json

Wave A3 (2026-07-23), fable 裁定 R4: 回測需要同期大盤基準才能回答「+2.24% 是
alpha 還是 beta」。內部 data/market_pulse/*.json 只有 2026-07-08 起(缺 7/10,
經查證 TWSE 當日未開盤——非資料缺失,是假日);5/08–7/07 的大盤收盤沒有既有
來源,須另外回填。

Sources (both TWSE 公開合法免費, no auth):
  1. data/market_pulse/<date>.json 的 taiex.close/change/change_pct — 2026-07-08
     起逐日快照(pipeline 既有副產物,信任度最高,直接沿用其 source 註記)。
  2. TWSE FMTQIK(每月市場成交資訊,發行量加權股價指數欄)— 一次取一整月,
     用於 5/08–7/07(以及任何 market_pulse 缺漏的日子)。比逐日打 MI_INDEX
     省 API 呼叫數(3 次 vs ~40 次),同樣是 TWSE 官方公開端點。
     https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json&date=YYYYMM01

Every entry in the output records its `source` so downstream (backtest alpha
calc) can distinguish pulse-derived vs FMTQIK-backfilled values if ever needed.

Usage:
    python -m tools.fetch_taiex_history            # merge + backfill, write file
    python -m tools.fetch_taiex_history --dry-run   # print summary, don't write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.request
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

MARKET_PULSE_DIR = _AI_STOCK / "data" / "market_pulse"
OUT_FILE = _AI_STOCK / "data" / "taiex_history.json"

BACKFILL_START = "2026-05-08"   # R4: 回測起點
FMTQIK_MONTHS = ["20260501", "20260601", "20260701"]  # 涵蓋 5/08–7/23

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


# ── Source 1: data/market_pulse/*.json ──────────────────────────────────────

def _from_market_pulse() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not MARKET_PULSE_DIR.is_dir():
        return out
    for f in sorted(MARKET_PULSE_DIR.glob("????-??-??.json")):
        date = f.stem
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        taiex = d.get("taiex") or {}
        close = taiex.get("close")
        if close is None:
            continue
        out[date] = {
            "close": close,
            "change": taiex.get("change"),
            "change_pct": taiex.get("change_pct"),
            "source": f"market_pulse:{taiex.get('source', 'unknown')}",
        }
    return out


# ── Source 2: TWSE FMTQIK (monthly 發行量加權股價指數) ───────────────────────

def _roc_to_iso(roc_date: str) -> str | None:
    """'115/07/08' (民國年) → '2026-07-08'."""
    parts = roc_date.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        y = int(parts[0]) + 1911
        m = int(parts[1])
        d = int(parts[2])
    except ValueError:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def _n(s: Any) -> float | None:
    try:
        return float(str(s).replace(",", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def _fetch_fmtqik_month(yyyymm01: str, *, timeout: int = 15) -> dict[str, dict[str, Any]]:
    """One TWSE FMTQIK call → {iso_date: {close, change, change_pct, source}} for that month."""
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json&date={yyyymm01}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8-sig"))
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(data, dict) or data.get("stat") != "OK":
        return out
    for row in data.get("data", []):
        if len(row) < 6:
            continue
        iso = _roc_to_iso(row[0])
        close = _n(row[4])
        change = _n(row[5])
        if iso is None or close is None:
            continue
        change_pct = round(change / (close - change) * 100, 2) if change is not None and (close - change) else None
        out[iso] = {
            "close": close,
            "change": change,
            "change_pct": change_pct,
            "source": "twse-FMTQIK",
        }
    return out


def _from_fmtqik(months: list[str], *, sleep_s: float = 2.0) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i, ym in enumerate(months):
        if i > 0:
            time.sleep(sleep_s)   # 節流,對齊 fetch_market_pulse.py 既有呼叫節奏
        try:
            out.update(_fetch_fmtqik_month(ym))
        except Exception as e:
            print(f"[taiex_history] FMTQIK {ym} failed: {e}", file=sys.stderr)
    return out


# ── Merge ────────────────────────────────────────────────────────────────────

def build(*, live_fetch: bool = True) -> dict[str, dict[str, Any]]:
    """Merge market_pulse (authoritative for 7/08+ close) with FMTQIK backfill.

    market_pulse's `close` wins on overlap (it's the pipeline's own same-day
    capture); FMTQIK fills everything else >= BACKFILL_START. `close` alone
    decides provenance (`source`); `change`/`change_pct` are then RECOMPUTED
    from the merged close series (previous available date, which may fall
    before BACKFILL_START — kept only as a lookback anchor, not in the output)
    rather than trusted verbatim from either source. Reason: some
    data/market_pulse/*.json snapshots carry a known upstream sign bug (見
    tools/fetch_market_pulse.py 的 07/17 事故註解 — 同一批 MI_INDEX 欄位解析
    偶爾 change 正負號與 change_pct 對不上,例如 2026-07-09.json:
    change=+379.8 但 change_pct=-0.83)。回測用的是 close 序列本身算報酬,不
    受影響;但既然本檔是新建檔,順手用 close 差自己重算,避免把上游已知的
    正負號 bug 原樣搬進一份「乾淨」的新資料檔。
    """
    pulse = _from_market_pulse()
    fmtqik = _from_fmtqik(FMTQIK_MONTHS) if live_fetch else {}

    closes: dict[str, tuple[float, str]] = {   # date -> (close, source)
        date: (entry["close"], "twse-FMTQIK") for date, entry in fmtqik.items()
    }
    for date, entry in pulse.items():          # pulse wins on overlap
        closes[date] = (entry["close"], entry["source"])

    ordered_dates = sorted(closes)
    merged: dict[str, dict[str, Any]] = {}
    prev_close: float | None = None
    for date in ordered_dates:
        close, source = closes[date]
        change = round(close - prev_close, 2) if prev_close is not None else None
        change_pct = round(change / prev_close * 100, 2) if change is not None and prev_close else None
        if date >= BACKFILL_START:
            merged[date] = {
                "close": close, "change": change, "change_pct": change_pct, "source": source,
            }
        prev_close = close
    return merged


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill data/taiex_history.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    merged = build()
    if not merged:
        print("[taiex_history] no data collected — nothing written", file=sys.stderr)
        return 1

    dates = sorted(merged)
    pulse_n = sum(1 for e in merged.values() if e["source"].startswith("market_pulse"))
    fmtqik_n = sum(1 for e in merged.values() if e["source"] == "twse-FMTQIK")
    print(f"[taiex_history] {len(merged)} dates  {dates[0]}→{dates[-1]}  "
          f"(market_pulse={pulse_n}, twse-FMTQIK={fmtqik_n})", file=sys.stderr)

    if args.dry_run:
        return 0

    payload = {
        "_comment": (
            "TAIEX 日收盤回填 — Wave A3(2026-07-23),fable 裁定 R4。"
            "來源見各筆 source(market_pulse:* = 內部 pipeline 同日快照;"
            "twse-FMTQIK = TWSE 官方每月市場成交資訊回填)。"
        ),
        "generated_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backfill_start": BACKFILL_START,
        "dates": merged,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[taiex_history] wrote {OUT_FILE.relative_to(_AI_STOCK)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
