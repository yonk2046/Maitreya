"""core/prices.py — 逐日全市場行情(I 態,`data/prices/<date>.json`)。

**為什麼需要它**(AUDIT-golden-list-20260922 / PLAN-yearly-backtest B1+B3):
快照的 `stocks[]` 只有「當天在主力買超榜上」的股票,所以回測
  ① 撮合價只能讀快照的 `open`(2026-09-23 前還是前一交易日的開盤),
  ② 持倉一掉出榜單就沒有價格 —— 停損、逐日估值全部停擺(持有日的 53%)。
價格是 I 態事實、不是判斷,故放在快照之外的逐日檔;回測仍只從快照讀「當時的判斷」
(憲法不變量 8:回測永不重建歷史判斷)。

來源 = 與 A4 同一份 TWSE MI_INDEX?date=(全市場、按日期),由 pipeline 逐日落地;
5/08–9/22 由 tools/backfill_prices.py 一次性回補。WORM:既有檔不覆寫(內容相同才略過)。
"""
from __future__ import annotations

import json
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
PRICES_DIR = _HERE.parent / "data" / "prices"

_cache: dict[str, dict] = {}


def load(date: str, base_dir: pathlib.Path | None = None) -> dict[str, dict]:
    """{ticker: {o,h,l,c,v}} for `date`; {} when the day has no file."""
    key = f"{base_dir or PRICES_DIR}|{date}"
    if key in _cache:
        return _cache[key]
    p = (base_dir or PRICES_DIR) / f"{date}.json"
    try:
        rows = json.loads(p.read_text(encoding="utf-8")).get("rows") or {}
    except (FileNotFoundError, ValueError):
        rows = {}
    _cache[key] = rows
    return rows


def get(date: str, ticker: str, field: str = "c", base_dir: pathlib.Path | None = None):
    return (load(date, base_dir).get(ticker) or {}).get(field)


def write_day(date: str, rows: dict[str, dict], base_dir: pathlib.Path | None = None) -> bool:
    """Write one day's file. Returns True when written, False when an identical file exists.

    WORM-ish: an existing file is never silently changed — a differing payload raises,
    so a re-fetch that disagrees with the archived session data is a loud failure.
    """
    d = base_dir or PRICES_DIR
    d.mkdir(parents=True, exist_ok=True)
    payload = {"date": date, "source": "twse-mi-index", "rows": rows}
    p = d / f"{date}.json"
    if p.exists():
        old = json.loads(p.read_text(encoding="utf-8"))
        if old.get("rows") == rows:
            return False
        raise ValueError(f"prices/{date}.json already exists with different rows (WORM)")
    p.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                 encoding="utf-8")
    _cache.pop(f"{d}|{date}", None)
    return True


def rows_from_quotes(quotes: dict[str, dict]) -> dict[str, dict]:
    """fetch_twse._parse_mi_index_quotes' `quotes` → the compact {o,h,l,c,v} rows."""
    out: dict[str, dict] = {}
    for code, q in (quotes or {}).items():
        row = {k: v for k, v in (("o", q.get("open")), ("h", q.get("high")),
                                 ("l", q.get("low")), ("c", q.get("close")),
                                 ("v", q.get("vol"))) if v is not None}
        if row.get("c") is not None:
            out[code] = row
    return out
