"""Industry backfill — Wave A3 (2026-07-23).

Covers `data.adapters.legacy._load_industry_map` + the date-cutover gate:
  - dates on/after the cutover get `industry` populated from the static
    data/industry_map.json table;
  - dates before the cutover stay exactly as-was (industry=None), so
    already-committed historical snapshots keep replaying byte-identical;
  - the lookup is identical under live AND replay (paths_override) — unlike
    branch mtime, there is no live-only fallback here, so both modes must
    agree for any date on/after the cutover (future-replay safety).
  - a ticker absent from the static table stays None (no crash, no fake data).
"""
from __future__ import annotations

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from data.adapters.legacy import adapt_legacy  # noqa: E402


def _make_env(tmp_path: pathlib.Path, tickers: list[str], target_date: str) -> dict[str, pathlib.Path]:
    root = tmp_path
    (root / "data").mkdir(parents=True, exist_ok=True)
    branches_dir = root / "data" / "branches"
    branches_dir.mkdir(parents=True, exist_ok=True)
    today = {
        "tradingDate": target_date,
        "mainForceBuy": [
            {"code": t, "name": f"股{t}", "rank": i + 1, "close": 50.0, "chgPct": 1.0,
             "buyVol": 300}
            for i, t in enumerate(tickers)
        ],
    }
    (root / "data" / "today.json").write_text(json.dumps(today, ensure_ascii=False), encoding="utf-8")
    return {
        "root": root,
        "today_json": root / "data" / "today.json",
        "branches_dir": branches_dir,
        "snapshots": root / "data" / "snapshots",
    }


# 1101 台泥 is in the real committed data/industry_map.json (水泥工業).
KNOWN_TICKER = "1101"
KNOWN_INDUSTRY = "水泥工業"


def test_on_cutover_date_industry_populated_live(tmp_path):
    paths = _make_env(tmp_path, [KNOWN_TICKER], "2026-07-24")
    out = adapt_legacy(date="2026-07-24", paths_override=paths, branch_mtime_fallback=True)
    ri = out["raw_inputs_per_ticker"][KNOWN_TICKER]
    assert ri.get("industry") == KNOWN_INDUSTRY


def test_on_cutover_date_industry_populated_replay(tmp_path):
    # replay mode (mtime_fallback off) must agree with live — same static
    # file, no live-only signal involved for this field.
    paths = _make_env(tmp_path, [KNOWN_TICKER], "2026-07-24")
    out = adapt_legacy(date="2026-07-24", paths_override=paths, branch_mtime_fallback=False)
    ri = out["raw_inputs_per_ticker"][KNOWN_TICKER]
    assert ri.get("industry") == KNOWN_INDUSTRY


def test_before_cutover_date_industry_stays_absent(tmp_path):
    # 2026-07-23 is the last date whose snapshot is already committed as-was
    # (industry=None) — must NOT retroactively gain a value.
    paths = _make_env(tmp_path, [KNOWN_TICKER], "2026-07-23")
    out = adapt_legacy(date="2026-07-23", paths_override=paths, branch_mtime_fallback=True)
    ri = out["raw_inputs_per_ticker"][KNOWN_TICKER]
    assert "industry" not in ri


def test_unknown_ticker_stays_absent_after_cutover(tmp_path):
    paths = _make_env(tmp_path, ["0000"], "2026-07-24")
    out = adapt_legacy(date="2026-07-24", paths_override=paths, branch_mtime_fallback=True)
    ri = out["raw_inputs_per_ticker"]["0000"]
    assert "industry" not in ri


def test_static_map_covers_current_universe_and_tier_a():
    from core.engine_params import TIER_A

    raw = json.loads((_AI_STOCK / "data" / "industry_map.json").read_text(encoding="utf-8"))
    tickers = raw["tickers"]
    for t in TIER_A:
        assert t in tickers, f"TIER_A ticker {t} missing from data/industry_map.json"
    latest = json.loads((_AI_STOCK / "reports" / "2026-07-23.json").read_text(encoding="utf-8"))
    for s in latest.get("stocks", []):
        t = s["ticker"]
        assert t in tickers, f"universe ticker {t} missing from data/industry_map.json"
