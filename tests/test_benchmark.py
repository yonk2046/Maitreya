"""core/benchmark.py — TAIEX as-of lookup + period return. Wave A3 (2026-07-23)."""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.benchmark import as_of_close, period_return_pct  # noqa: E402

HISTORY = {
    "2026-05-08": {"close": 41603.94},
    "2026-05-13": {"close": 40800.00},
    "2026-05-14": {"close": 41000.00},
}


def test_as_of_close_exact_match():
    assert as_of_close(HISTORY, "2026-05-13") == 40800.00


def test_as_of_close_falls_back_to_nearest_prior():
    # 2026-05-10 (Sunday-ish gap) has no entry — should use 2026-05-08.
    assert as_of_close(HISTORY, "2026-05-10") == 41603.94


def test_as_of_close_before_earliest_returns_none():
    assert as_of_close(HISTORY, "2026-05-01") is None


def test_as_of_close_empty_history_returns_none():
    assert as_of_close({}, "2026-05-08") is None


def test_period_return_pct_basic():
    ret = period_return_pct(HISTORY, "2026-05-08", "2026-05-14")
    assert ret is not None
    assert round(ret, 6) == round((41000.00 - 41603.94) / 41603.94, 6)


def test_period_return_pct_unresolvable_endpoint_is_none():
    assert period_return_pct(HISTORY, "2026-04-01", "2026-05-14") is None


def test_period_return_pct_same_date_is_zero():
    assert period_return_pct(HISTORY, "2026-05-08", "2026-05-08") == 0.0


def test_real_taiex_history_file_loads_and_is_well_formed():
    import json
    raw = json.loads((_AI_STOCK / "data" / "taiex_history.json").read_text(encoding="utf-8"))
    dates = raw["dates"]
    assert len(dates) >= 50
    assert "2026-07-23" in dates
    for d, entry in dates.items():
        assert isinstance(entry["close"], (int, float))
        assert entry["source"]
        if entry["change"] is not None and entry["change_pct"] is not None:
            # sign of change must match sign of change_pct (regression guard for
            # the upstream market_pulse sign bug this file intentionally avoids)
            assert (entry["change"] >= 0) == (entry["change_pct"] >= 0)
