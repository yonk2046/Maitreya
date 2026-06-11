"""TDCC 集保戶股權分散表 adapter.

Data source: TDCC OpenData (opendata.tdcc.com.tw), id=1-5
CSV format:  資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%
Updated every Friday after market close.

Holding grade → lot range (1 lot = 1,000 shares):
  1  : 1-999 shares         (< 1 lot)
  2  : 1,000-5,000 shares   (1-5 lots)
  3  : 5,001-10,000         (5-10 lots)
  4  : 10,001-15,000        (10-15 lots)
  5  : 15,001-20,000        (15-20 lots)
  6  : 20,001-30,000        (20-30 lots)
  7  : 30,001-40,000        (30-40 lots)
  8  : 40,001-50,000        (40-50 lots)
  9  : 50,001-100,000       (50-100 lots)
  10 : 100,001-200,000      (100-200 lots)
  11 : 200,001-400,000      (200-400 lots)
  12 : 400,001-600,000      (400-600 lots)  ┐
  13 : 600,001-800,000      (600-800 lots)  │ ≥ 400 lots (large_holder_400)
  14 : 800,001-1,000,000    (800-1000 lots) │
  15 : 1,000,001+           (≥ 1000 lots)  ┘  also = large_holder_1000
  16 : 外資及陸資 — foreign/mainland institutional (excluded from 大戶 pct)
  17 : 合計 — grand total (用於 shareholder_count)

WORM safety note: fetch_and_save() writes to data/tdcc/ which is NOT in
the WORM monitor scope (only data/today.json, data/branches/, data/snapshots/
are monitored). Always call fetch_and_save() BEFORE running run_pipeline.py.

Public API:
    fetch_and_save(tdcc_dir, force=False) -> pathlib.Path
    load_for_date(date_iso, tdcc_dir)     -> dict[str, dict]
    enrich_universe(raw_inputs, tdcc_map) -> None  (mutates in-place)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import pathlib
import urllib.request
from typing import Any

TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5&key=Open"

# Grades whose 比例% sum to large_holder_400_pct (≥ 400,000 shares = ≥ 400 lots)
_LARGE_400_GRADES: frozenset[int] = frozenset({12, 13, 14, 15})
# Grade whose 比例% equals large_holder_1000_pct (≥ 1,000,000 shares = ≥ 1000 lots)
_LARGE_1000_GRADE: int = 15
# Grade that holds the grand total row
_TOTAL_GRADE: int = 17


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_csv(url: str = TDCC_URL, timeout: int = 30) -> str:
    """Download TDCC CSV and return raw text. TDCC serves UTF-8 with BOM."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SCD-Engine/1.4)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8-sig")


def _parse_csv(text: str) -> tuple[str, dict[str, dict[str, float | int | None]]]:
    """Parse TDCC CSV text.

    Returns:
        (tdcc_date_str, stocks_dict)
        tdcc_date_str: "YYYYMMDD" from 資料日期 column
        stocks_dict: {
            ticker: {
                "shareholder_count":    int | None,
                "large_holder_400_pct": float,
                "large_holder_1000_pct": float,
            }
        }
    """
    reader = csv.DictReader(io.StringIO(text))
    # Accumulate per ticker: {ticker: {grade: (people, pct)}}
    acc: dict[str, dict[int, tuple[int, float]]] = {}
    tdcc_date = ""

    for row in reader:
        raw_date = (row.get("資料日期") or "").strip()
        if raw_date and not tdcc_date:
            tdcc_date = raw_date
        ticker = (row.get("證券代號") or "").strip()
        if not ticker:
            continue
        try:
            grade  = int((row.get("持股分級") or "0").strip())
            people = int((row.get("人數") or "0").strip().replace(",", ""))
            pct    = float((row.get("占集保庫存數比例%") or "0").strip())
        except (ValueError, AttributeError):
            continue
        if ticker not in acc:
            acc[ticker] = {}
        acc[ticker][grade] = (people, pct)

    stocks: dict[str, dict[str, float | int | None]] = {}
    for ticker, grades in acc.items():
        # shareholder_count: headcount from grade-17 total row
        total_row = grades.get(_TOTAL_GRADE)
        shareholder_count: int | None = total_row[0] if total_row else None

        # large_holder_400_pct: sum of % for grades 12–15
        large_400_pct = sum(grades[g][1] for g in _LARGE_400_GRADES if g in grades)

        # large_holder_1000_pct: % for grade 15 only
        grade_15 = grades.get(_LARGE_1000_GRADE)
        large_1000_pct = grade_15[1] if grade_15 else 0.0

        stocks[ticker] = {
            "shareholder_count":     shareholder_count,
            "large_holder_400_pct":  round(large_400_pct, 4),
            "large_holder_1000_pct": round(large_1000_pct, 4),
        }

    return tdcc_date, stocks


# ---------------------------------------------------------------------------
# Fetch & save
# ---------------------------------------------------------------------------

def fetch_and_save(
    tdcc_dir: pathlib.Path | str,
    force: bool = False,
    url: str = TDCC_URL,
) -> pathlib.Path:
    """Download and cache the latest TDCC distribution CSV.

    Output: <tdcc_dir>/<YYYYMMDD>.json (where YYYYMMDD is TDCC's 資料日期).
    Skips download if the cache file already exists unless force=True.

    Returns the path of the (new or existing) cache file.
    """
    tdcc_dir = pathlib.Path(tdcc_dir)
    tdcc_dir.mkdir(parents=True, exist_ok=True)

    csv_text = _fetch_csv(url)
    tdcc_date, stocks = _parse_csv(csv_text)
    if not tdcc_date:
        raise ValueError("Could not parse 資料日期 from TDCC CSV — format may have changed")

    out_path = tdcc_dir / f"{tdcc_date}.json"
    if out_path.exists() and not force:
        return out_path  # already cached — skip write

    payload = {
        "tdcc_date":   tdcc_date,
        "fetched_at":  dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stock_count": len(stocks),
        "stocks":      stocks,
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return out_path


# ---------------------------------------------------------------------------
# Load & delta
# ---------------------------------------------------------------------------

def _tdcc_yyyymmdd_to_iso(d: str) -> str:
    """'20260605' → '2026-06-05'."""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _list_cache_files(tdcc_dir: pathlib.Path) -> list[tuple[dt.date, pathlib.Path]]:
    """Return (date, path) pairs for all ????????.json files, oldest first."""
    result: list[tuple[dt.date, pathlib.Path]] = []
    for f in sorted(tdcc_dir.glob("????????.json")):
        try:
            d = dt.date.fromisoformat(_tdcc_yyyymmdd_to_iso(f.stem))
            result.append((d, f))
        except ValueError:
            pass
    return result


def load_for_date(
    date_iso: str,
    tdcc_dir: pathlib.Path | str,
) -> dict[str, dict[str, Any]]:
    """Load TDCC data for the most recent Friday on or before date_iso.

    Also loads the previous week's cache file to compute week-over-week deltas.

    Returns:
        {ticker: {
            "shareholder_count":            int | None,
            "shareholder_count_delta_pct":  float | None,
            "large_holder_400_pct":         float,
            "large_holder_400_delta_pct":   float | None,
            "large_holder_1000_pct":        float,
            "large_holder_1000_delta_pct":  float | None,
            "tdcc_date":                    str,   # YYYYMMDD
            "tdcc_fetched_at":              str,   # ISO UTC
        }}
    Returns empty dict if no cache file found.
    """
    tdcc_dir = pathlib.Path(tdcc_dir)
    if not tdcc_dir.is_dir():
        return {}

    files = _list_cache_files(tdcc_dir)
    if not files:
        return {}

    target = dt.date.fromisoformat(date_iso)
    eligible = [(d, f) for d, f in files if d <= target]
    if not eligible:
        return {}

    cur_date, cur_file = eligible[-1]
    prev_stocks: dict = {}
    if len(eligible) >= 2:
        _, prev_file = eligible[-2]
        try:
            prev_stocks = json.loads(prev_file.read_text(encoding="utf-8")).get("stocks", {})
        except Exception:
            pass

    cur_payload = json.loads(cur_file.read_text(encoding="utf-8"))
    cur_stocks:  dict = cur_payload.get("stocks", {})
    tdcc_date    = cur_payload.get("tdcc_date", cur_file.stem)
    fetched_at   = cur_payload.get("fetched_at", "")

    result: dict[str, dict[str, Any]] = {}
    for ticker, curr in cur_stocks.items():
        prev = prev_stocks.get(ticker, {})

        sc      = curr.get("shareholder_count")
        prev_sc = prev.get("shareholder_count")
        sc_delta: float | None = None
        if sc is not None and prev_sc:
            sc_delta = round((sc - prev_sc) / prev_sc * 100, 4)

        l400      = curr.get("large_holder_400_pct", 0.0)
        prev_l400 = prev.get("large_holder_400_pct")
        l400_delta: float | None = None if prev_l400 is None else round(l400 - prev_l400, 4)

        l1000      = curr.get("large_holder_1000_pct", 0.0)
        prev_l1000 = prev.get("large_holder_1000_pct")
        l1000_delta: float | None = None if prev_l1000 is None else round(l1000 - prev_l1000, 4)

        result[ticker] = {
            "shareholder_count":           sc,
            "shareholder_count_delta_pct": sc_delta,
            "large_holder_400_pct":        l400,
            "large_holder_400_delta_pct":  l400_delta,
            "large_holder_1000_pct":       l1000,
            "large_holder_1000_delta_pct": l1000_delta,
            "tdcc_date":                   tdcc_date,
            "tdcc_fetched_at":             fetched_at,
        }

    return result


# ---------------------------------------------------------------------------
# Enrich universe (called from adapt_legacy)
# ---------------------------------------------------------------------------

_ENRICH_FIELDS = (
    "shareholder_count",
    "shareholder_count_delta_pct",
    "large_holder_400_pct",
    "large_holder_400_delta_pct",
    "large_holder_1000_pct",
    "large_holder_1000_delta_pct",
)


def enrich_universe(
    raw_inputs_per_ticker: dict[str, dict],
    tdcc_map: dict[str, dict[str, Any]],
) -> None:
    """Merge TDCC fields into raw_inputs_per_ticker in-place.

    Only touches the 6 schema fields + internal _tdcc_* metadata.
    Never overwrites fields already set by earlier adapter stages.
    Safe to call with an empty tdcc_map (no-op per ticker).
    """
    for ticker, ri in raw_inputs_per_ticker.items():
        entry = tdcc_map.get(ticker)
        if entry is None:
            continue
        for field in _ENRICH_FIELDS:
            ri[field] = entry[field]
        ri["_tdcc_date"]       = entry["tdcc_date"]
        ri["_tdcc_fetched_at"] = entry["tdcc_fetched_at"]
