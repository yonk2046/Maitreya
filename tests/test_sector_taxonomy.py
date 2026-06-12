"""Sector taxonomy tests — official industry map + curated overlay.

Covers:
  - INDUSTRY_CODE_TO_SECTOR maps every code to a real SECTOR_TAXONOMY key
  - ticker_sector() resolution order: curated overlay > official map > other
  - known misclassification fixes (5880, 6505, 5347, 9945, 2385)
  - industry_adapter pure parsers (TWSE + TPEx field shapes)
  - cache loader graceful fallback when file absent/corrupt
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import sector_intelligence as si  # noqa: E402
from data.adapters import industry_adapter as ia  # noqa: E402


# ----------------------------------------------------------------------
# Static mapping integrity
# ----------------------------------------------------------------------

def test_every_industry_code_maps_to_real_sector():
    for code, sector in si.INDUSTRY_CODE_TO_SECTOR.items():
        assert sector in si.SECTOR_TAXONOMY, (
            f"code {code} maps to unknown sector '{sector}'"
        )


def test_official_taxonomy_covers_all_twse_codes():
    """All 33 active TWSE/TPEx industry codes must be present."""
    expected = {
        "01", "02", "03", "04", "05", "06", "08", "09", "10", "11", "12",
        "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24",
        "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35",
        "36", "37", "38",
    }
    assert expected.issubset(set(si.INDUSTRY_CODE_TO_SECTOR.keys()))


def test_taxonomy_metadata_complete():
    for key, meta in si.SECTOR_TAXONOMY.items():
        assert meta.get("zh") and meta.get("en"), f"{key}: missing zh/en label"
        assert meta.get("color", "").startswith("#"), f"{key}: missing color"


# ----------------------------------------------------------------------
# Resolution order
# ----------------------------------------------------------------------

@pytest.fixture()
def fake_industry_cache(tmp_path, monkeypatch):
    """Point the loader at a temp cache file and reset memoization."""
    def _install(tickers: dict[str, str]) -> None:
        f = tmp_path / "industry_map.json"
        f.write_text(json.dumps({"fetched_at": "2026-06-12T00:00:00Z",
                                 "tickers": tickers}), encoding="utf-8")
        monkeypatch.setattr(si, "_INDUSTRY_MAP_FILE", f)
        si._reset_industry_cache()
    yield _install
    si._reset_industry_cache()


def test_curated_overlay_wins_over_official(fake_industry_cache):
    # 2330 is curated semiconductor; give it a bogus official code
    fake_industry_cache({"2330": "17"})
    assert si.ticker_sector("2330") == "semiconductor"


def test_official_map_fills_uncurated_tickers(fake_industry_cache):
    fake_industry_cache({"9999": "22"})
    assert si.ticker_sector("9999") == "biotech"


def test_unknown_ticker_falls_to_other(fake_industry_cache):
    fake_industry_cache({})
    assert si.ticker_sector("0000") == "other"


def test_missing_cache_file_degrades_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "_INDUSTRY_MAP_FILE", tmp_path / "nope.json")
    si._reset_industry_cache()
    try:
        # curated still works, uncurated → other, no exception
        assert si.ticker_sector("2330") == "semiconductor"
        assert si.ticker_sector("9999") == "other"
    finally:
        si._reset_industry_cache()


# ----------------------------------------------------------------------
# Misclassification fixes (2026-06-12)
# ----------------------------------------------------------------------

def test_fixed_misclassifications(fake_industry_cache):
    fake_industry_cache({
        "5880": "17",  # 合庫金 → financials
        "9945": "18",  # 潤泰全 → consumer
        "5347": "24",  # 世界先進 → semiconductor
        "2385": "25",  # 群光 → electronics
        "6505": "23",  # 台塑化 (still curated energy_power — overlay wins)
    })
    assert si.ticker_sector("5880") == "financials"
    assert si.ticker_sector("9945") == "consumer"
    assert si.ticker_sector("5347") == "semiconductor"
    assert si.ticker_sector("2385") == "electronics"
    assert si.ticker_sector("6505") == "energy_power"
    # and the bad curated assignments are gone:
    assert "5880" not in si.SECTOR_TAXONOMY["shipping"]["tickers"]
    assert "6505" not in si.SECTOR_TAXONOMY["networking"]["tickers"]
    assert "5347" not in si.SECTOR_TAXONOMY["energy_power"]["tickers"]
    assert "2385" not in si.SECTOR_TAXONOMY["semiconductor"]["tickers"]


# ----------------------------------------------------------------------
# Adapter parsers (pure functions)
# ----------------------------------------------------------------------

def test_parse_twse_extracts_code():
    rows = [
        {"公司代號": "2330", "產業別": "24", "公司簡稱": "台積電"},
        {"公司代號": " 1101 ", "產業別": " 01 "},
        {"公司代號": "", "產業別": "01"},          # dropped
        {"公司簡稱": "no-code"},                    # dropped
    ]
    assert ia.parse_twse(rows) == {"2330": "24", "1101": "01"}


def test_parse_tpex_extracts_code():
    rows = [
        {"SecuritiesCompanyCode": "5347", "SecuritiesIndustryCode": "24"},
        {"SecuritiesCompanyCode": "1240", "SecuritiesIndustryCode": "33"},
        {"SecuritiesCompanyCode": "", "SecuritiesIndustryCode": "02"},  # dropped
    ]
    assert ia.parse_tpex(rows) == {"5347": "24", "1240": "33"}


def test_cache_age_none_when_absent(tmp_path):
    assert ia.cache_age_days(tmp_path) is None


def test_cache_age_none_when_corrupt(tmp_path):
    (tmp_path / ia.CACHE_FILENAME).write_text("not json", encoding="utf-8")
    assert ia.cache_age_days(tmp_path) is None


def test_build_sector_map_uses_official_fallback(fake_industry_cache):
    fake_industry_cache({"9914": "37"})  # 美利達 → consumer (運動休閒)
    snaps = [{"stocks": [{"ticker": "2330"}, {"ticker": "9914"}, {"ticker": "0000"}]}]
    sm = si.build_sector_map(snaps)
    assert sm.sector_of("2330") == "semiconductor"
    assert sm.sector_of("9914") == "consumer"
    assert sm.sector_of("0000") == "other"
