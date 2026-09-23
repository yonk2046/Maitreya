"""One-off: build data/prices/<date>.json for the dates that predate A6 landing.

(Not to be confused with tools/backfill_prices.py — that one repairs prices inside the
SANDBOX reconstruction under data/backfill/; this one lands the real per-session
full-market OHLCV the backtest fills from.)

Source = TWSE MI_INDEX?date= (same endpoint the pipeline now lands daily). Reads a
local cache dir first (--cache), so an already-fetched corpus is not re-downloaded.
WORM: existing files are never overwritten (core.prices.write_day raises on a diff).

    python3 tools/backfill_daily_prices.py --cache "/path/to/px" [--date-from 2026-05-08]
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

from core import prices as _prices  # noqa: E402


def _arg(name, default=None):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def main() -> int:
    cache = pathlib.Path(_arg("--cache", "")) if _arg("--cache") else None
    date_from = _arg("--date-from", "2026-05-08")
    idx = json.loads((_ROOT / "reports" / "index.json").read_text(encoding="utf-8"))["snapshots"]
    dates = sorted(d for d, e in idx.items()
                   if "example" not in d and "example" not in e["current"] and d >= date_from)
    from fetch_twse import fetch_quotes_by_date
    wrote = skipped = failed = 0
    for d in dates:
        if (_prices.PRICES_DIR / f"{d}.json").exists():
            skipped += 1
            continue
        rows = {}
        if cache and (cache / f"{d}.json").exists():          # pre-fetched OHLCV cache
            rows = {k: {kk: vv for kk, vv in v.items() if vv is not None}
                    for k, v in (json.loads((cache / f"{d}.json").read_text()).get("rows") or {}).items()
                    if not k.startswith("00") and v.get("c") is not None}
        if not rows:
            try:
                rows = _prices.rows_from_quotes(fetch_quotes_by_date(d.replace("-", ""))["marketQuotes"])
                time.sleep(3)
            except Exception as e:
                print(f"{d}: FAILED {e}", file=sys.stderr)
                failed += 1
                continue
        _prices.write_day(d, rows)
        wrote += 1
        print(f"{d}: {len(rows)} rows")
    print(f"wrote={wrote} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
