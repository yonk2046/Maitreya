"""Industry classification adapter — TWSE + TPEx official 產業別 codes.

Downloads the official company-basics open data and caches a compact
{ticker: industry_code} map to data/industry/industry_map.json.

Sources (both return full-market JSON arrays):
  TWSE 上市:  https://openapi.twse.com.tw/v1/opendata/t187ap03_L
              fields: 公司代號, 產業別, ...
  TPEx 上櫃:  https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O
              fields: SecuritiesCompanyCode, SecuritiesIndustryCode, ...

Both exchanges share the same industry-code family (01 水泥 … 38 居家生活).
The code → sector-group mapping lives in core/sector_intelligence.py
(INDUSTRY_CODE_TO_SECTOR); this adapter only fetches and caches raw codes.

Refresh policy: industry assignment changes rarely (TWSE adjusts at most
quarterly). fetch_and_save() skips the download when the cache is younger
than MAX_AGE_DAYS, so it is safe to call from the daily pipeline.

NOT WORM: data/industry/ is a refreshable cache, same policy as data/tdcc/.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import urllib.request
from typing import Any

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

MAX_AGE_DAYS = 30
CACHE_FILENAME = "industry_map.json"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Pure parsers (unit-testable, no I/O)
# ---------------------------------------------------------------------------

def parse_twse(records: list[dict[str, Any]]) -> dict[str, str]:
    """TWSE t187ap03_L rows → {ticker: industry_code}."""
    out: dict[str, str] = {}
    for r in records:
        ticker = str(r.get("公司代號", "")).strip()
        code = str(r.get("產業別", "")).strip()
        if ticker and code:
            out[ticker] = code
    return out


def parse_tpex(records: list[dict[str, Any]]) -> dict[str, str]:
    """TPEx mopsfin_t187ap03_O rows → {ticker: industry_code}."""
    out: dict[str, str] = {}
    for r in records:
        ticker = str(r.get("SecuritiesCompanyCode", "")).strip()
        code = str(r.get("SecuritiesIndustryCode", "")).strip()
        if ticker and code:
            out[ticker] = code
    return out


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------

def _http_get_json(url: str, timeout: int = 60) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers={
        "accept": "application/json",
        "User-Agent": _UA,
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cache_path(industry_dir: pathlib.Path) -> pathlib.Path:
    return industry_dir / CACHE_FILENAME


def cache_age_days(industry_dir: pathlib.Path) -> float | None:
    """Age of the cache in days, or None if absent/corrupt."""
    f = cache_path(industry_dir)
    if not f.is_file():
        return None
    try:
        meta = json.loads(f.read_text(encoding="utf-8"))
        fetched = dt.datetime.fromisoformat(meta["fetched_at"].rstrip("Z"))
    except (json.JSONDecodeError, KeyError, ValueError):
        return None
    return (dt.datetime.utcnow() - fetched).total_seconds() / 86400.0


def fetch_and_save(industry_dir: pathlib.Path, *, force: bool = False) -> pathlib.Path:
    """Download both exchanges' industry codes and write the cache.

    Skips the download entirely when the cache is younger than MAX_AGE_DAYS
    (unless force=True). Returns the cache path.
    """
    out_file = cache_path(industry_dir)
    age = cache_age_days(industry_dir)
    if not force and age is not None and age < MAX_AGE_DAYS:
        return out_file

    twse_raw = _http_get_json(TWSE_URL)
    tpex_raw = _http_get_json(TPEX_URL)
    tickers = parse_twse(twse_raw)
    tpex_map = parse_tpex(tpex_raw)
    # TWSE wins on (unexpected) overlap — listed status is authoritative.
    for t, c in tpex_map.items():
        tickers.setdefault(t, c)

    if len(tickers) < 1000:
        raise RuntimeError(
            f"industry_adapter: only {len(tickers)} tickers parsed — "
            f"upstream format may have changed; refusing to overwrite cache"
        )

    industry_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {
            "twse": {"url": TWSE_URL, "count": len(parse_twse(twse_raw))},
            "tpex": {"url": TPEX_URL, "count": len(tpex_map)},
        },
        "tickers": dict(sorted(tickers.items())),
    }
    out_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    return out_file
