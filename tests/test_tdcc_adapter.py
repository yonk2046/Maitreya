"""Tests for data/adapters/tdcc_adapter.py.

Covers:
  - _parse_csv: grade→lot mapping, shareholder_count, large_holder_400/1000
  - load_for_date: nearest-Friday selection, week-over-week deltas, missing-file fallback
  - enrich_universe: field injection, ticker-not-in-map no-op
  - adapt_legacy integration: graceful DATA_WARNING when no TDCC cache
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from data.adapters.tdcc_adapter import (  # noqa: E402
    _LARGE_400_GRADES,
    _LARGE_1000_GRADE,
    _TOTAL_GRADE,
    _parse_csv,
    enrich_universe,
    load_for_date,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_csv(date_str: str, ticker: str, grade_rows: list[tuple[int, int, float]]) -> str:
    """Build minimal TDCC CSV text.

    grade_rows: [(grade, people, pct), ...]
    """
    lines = ["資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%"]
    for grade, people, pct in grade_rows:
        lines.append(f"{date_str},{ticker},{grade},{people},{people * 1000},{pct}")
    return "\n".join(lines) + "\n"


def _save_week(tdcc_dir: pathlib.Path, date_str: str, stocks: dict) -> pathlib.Path:
    """Write a fake TDCC cache file."""
    payload = {
        "tdcc_date": date_str,
        "fetched_at": f"20{date_str[2:6]}-{date_str[4:6]}-{date_str[6:8]}T08:00:00Z",
        "stock_count": len(stocks),
        "stocks": stocks,
    }
    path = tdcc_dir / f"{date_str}.json"
    path.write_text(json.dumps(payload))
    return path


# ---------------------------------------------------------------------------
# _parse_csv
# ---------------------------------------------------------------------------

class TestParseCsv:
    def test_shareholder_count_from_grade_17(self):
        csv = _make_csv("20260605", "2330", [
            (1,  5000, 0.10), (12, 200, 0.80), (13, 100, 0.40),
            (14,  50, 0.20), (15, 300, 90.00), (16,  10, 5.00),
            (17, 5660, 100.00),   # total row
        ])
        date, stocks = _parse_csv(csv)
        assert date == "20260605"
        assert stocks["2330"]["shareholder_count"] == 5660

    def test_large_holder_400_sums_grades_12_to_15(self):
        csv = _make_csv("20260605", "2330", [
            (11, 500, 3.00),   # NOT counted (< 400 lots)
            (12, 200, 1.00),   # counted
            (13, 100, 0.50),   # counted
            (14,  50, 0.25),   # counted
            (15, 300, 85.00),  # counted
            (16,  10, 5.00),   # NOT counted (foreign, excluded)
            (17, 1160, 100.00),
        ])
        _, stocks = _parse_csv(csv)
        assert stocks["2330"]["large_holder_400_pct"] == round(1.00 + 0.50 + 0.25 + 85.00, 4)

    def test_large_holder_1000_is_grade_15_only(self):
        csv = _make_csv("20260605", "2330", [
            (12, 200, 1.00), (13, 100, 0.50),
            (14,  50, 0.25), (15, 300, 85.00),
            (17, 650, 100.00),
        ])
        _, stocks = _parse_csv(csv)
        assert stocks["2330"]["large_holder_1000_pct"] == 85.00

    def test_missing_grade_15_gives_zero_1000(self):
        """Stocks with no grade-15 holders → 1000-lot pct = 0."""
        csv = _make_csv("20260605", "1101", [
            (12, 50, 0.30), (13, 20, 0.10), (17, 70, 100.00),
        ])
        _, stocks = _parse_csv(csv)
        assert stocks["1101"]["large_holder_1000_pct"] == 0.0

    def test_multiple_tickers(self):
        rows_2330 = [(15, 200, 90.00), (17, 500, 100.00)]
        rows_1303 = [(12, 10, 0.50), (17, 100, 100.00)]
        lines = ["資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%"]
        for g, p, pct in rows_2330:
            lines.append(f"20260605,2330,{g},{p},{p*1000},{pct}")
        for g, p, pct in rows_1303:
            lines.append(f"20260605,1303,{g},{p},{p*1000},{pct}")
        _, stocks = _parse_csv("\n".join(lines) + "\n")
        assert "2330" in stocks and "1303" in stocks
        assert stocks["2330"]["large_holder_1000_pct"] == 90.00
        assert stocks["1303"]["large_holder_1000_pct"] == 0.0


# ---------------------------------------------------------------------------
# load_for_date
# ---------------------------------------------------------------------------

class TestLoadForDate:
    @pytest.fixture
    def tdcc_dir(self, tmp_path):
        return tmp_path

    def _stocks(self, sc, l400, l1000):
        return {"2330": {"shareholder_count": sc,
                         "large_holder_400_pct": l400,
                         "large_holder_1000_pct": l1000}}

    def test_returns_empty_if_no_dir(self, tmp_path):
        result = load_for_date("2026-06-09", tmp_path / "nonexistent")
        assert result == {}

    def test_returns_empty_if_no_files(self, tdcc_dir):
        result = load_for_date("2026-06-09", tdcc_dir)
        assert result == {}

    def test_returns_empty_if_all_files_after_date(self, tdcc_dir):
        _save_week(tdcc_dir, "20260612", self._stocks(1000, 50.0, 30.0))
        result = load_for_date("2026-06-09", tdcc_dir)  # before 0612
        assert result == {}

    def test_picks_nearest_file_on_or_before_date(self, tdcc_dir):
        _save_week(tdcc_dir, "20260529", self._stocks(28000, 96.0, 95.0))
        _save_week(tdcc_dir, "20260605", self._stocks(28420, 97.0, 96.0))
        _save_week(tdcc_dir, "20260612", self._stocks(28500, 97.5, 96.5))
        result = load_for_date("2026-06-09", tdcc_dir)   # between 0605 and 0612
        assert result["2330"]["shareholder_count"] == 28420
        assert result["2330"]["tdcc_date"] == "20260605"

    def test_week_over_week_delta_shareholder_count(self, tdcc_dir):
        _save_week(tdcc_dir, "20260529", self._stocks(28000, 96.0, 95.0))
        _save_week(tdcc_dir, "20260605", self._stocks(28420, 97.0, 96.0))
        result = load_for_date("2026-06-09", tdcc_dir)
        expected_delta = round((28420 - 28000) / 28000 * 100, 4)
        assert result["2330"]["shareholder_count_delta_pct"] == expected_delta

    def test_week_over_week_delta_large_holder(self, tdcc_dir):
        _save_week(tdcc_dir, "20260529", self._stocks(28000, 96.0, 95.0))
        _save_week(tdcc_dir, "20260605", self._stocks(28420, 97.61, 96.15))
        result = load_for_date("2026-06-09", tdcc_dir)
        assert result["2330"]["large_holder_400_delta_pct"] == round(97.61 - 96.0, 4)
        assert result["2330"]["large_holder_1000_delta_pct"] == round(96.15 - 95.0, 4)

    def test_no_delta_when_only_one_file(self, tdcc_dir):
        _save_week(tdcc_dir, "20260605", self._stocks(28420, 97.61, 96.15))
        result = load_for_date("2026-06-09", tdcc_dir)
        assert result["2330"]["shareholder_count_delta_pct"] is None
        assert result["2330"]["large_holder_400_delta_pct"] is None
        assert result["2330"]["large_holder_1000_delta_pct"] is None

    def test_all_six_schema_fields_present(self, tdcc_dir):
        _save_week(tdcc_dir, "20260605", self._stocks(28420, 97.61, 96.15))
        result = load_for_date("2026-06-09", tdcc_dir)
        entry = result["2330"]
        for field in ("shareholder_count", "shareholder_count_delta_pct",
                      "large_holder_400_pct", "large_holder_400_delta_pct",
                      "large_holder_1000_pct", "large_holder_1000_delta_pct"):
            assert field in entry, f"missing field: {field}"


# ---------------------------------------------------------------------------
# enrich_universe
# ---------------------------------------------------------------------------

class TestEnrichUniverse:
    def _tdcc_map(self):
        return {
            "2330": {
                "shareholder_count": 28420,
                "shareholder_count_delta_pct": 1.5,
                "large_holder_400_pct": 97.61,
                "large_holder_400_delta_pct": 1.16,
                "large_holder_1000_pct": 96.15,
                "large_holder_1000_delta_pct": 1.15,
                "tdcc_date": "20260605",
                "tdcc_fetched_at": "2026-06-05T08:00:00Z",
            }
        }

    def test_injects_fields_for_matching_ticker(self):
        raw = {"2330": {"ticker": "2330"}}
        enrich_universe(raw, self._tdcc_map())
        assert raw["2330"]["shareholder_count"] == 28420
        assert raw["2330"]["large_holder_400_pct"] == 97.61
        assert raw["2330"]["_tdcc_date"] == "20260605"

    def test_does_not_touch_absent_ticker(self):
        raw = {"2317": {"ticker": "2317"}}
        enrich_universe(raw, self._tdcc_map())
        assert "shareholder_count" not in raw["2317"]
        assert "_tdcc_date" not in raw["2317"]

    def test_noop_on_empty_tdcc_map(self):
        raw = {"2330": {"ticker": "2330", "existing": True}}
        enrich_universe(raw, {})
        assert raw["2330"] == {"ticker": "2330", "existing": True}


# ---------------------------------------------------------------------------
# adapt_legacy integration: graceful degradation without cache
# ---------------------------------------------------------------------------

def test_adapt_legacy_emits_data_warning_when_no_tdcc_cache(tmp_path):
    """adapt_legacy must not crash when data/tdcc/ is empty or missing.
    It should emit a DATA_WARNING audit event and continue normally.

    We use paths_override to point at a temp dir that has no tdcc/ cache,
    while still pointing at the real today.json and branches so the adapter
    can build a valid output.
    """
    import pathlib
    from data.adapters.legacy import adapt_legacy, legacy_paths

    real_paths = legacy_paths()

    # Empty tdcc dir — no cache files
    fake_tdcc_dir = tmp_path / "tdcc"
    fake_tdcc_dir.mkdir()

    # Override only root so the tdcc search lands in our empty dir;
    # today_json and branches_dir keep pointing at real data.
    paths_override = {
        "root":         fake_tdcc_dir.parent,   # tmp_path as root
        "today_json":   real_paths["today_json"],
        "branches_dir": real_paths["branches_dir"],
    }

    out = adapt_legacy(paths_override=paths_override)
    tdcc_warnings = [
        e for e in out["audit_events"]
        if "tdcc" in e.get("step", "").lower()
    ]
    assert len(tdcc_warnings) == 1
    assert tdcc_warnings[0]["event"] == "DATA_WARNING"
    # Provenance should NOT include tdcc_weekly when no cache
    assert "tdcc_weekly" not in out["provenance_sources"]
