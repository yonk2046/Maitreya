"""T86 freshness gate (2026-07-03 lag bug).

HiNetCDN 307-blocks *today's* uncached T86 from datacenter IPs while serving
cached prior days → a stale t86 payload entered today.json and 7/03's
snapshot carried 7/02's FII. The fix stamps today.json["t86Date"] at fetch
time and _fii_published() refuses to pass when it mismatches tradingDate.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
_TOOLS = _AI_STOCK / "tools"
for p in (_AI_STOCK, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import daily  # noqa: E402


def _write_today(tmp_path, payload) -> pathlib.Path:
    f = tmp_path / "today.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


@pytest.fixture
def patch_today(tmp_path, monkeypatch):
    def _patch(payload):
        monkeypatch.setattr(daily, "TODAY_JSON", _write_today(tmp_path, payload))
    return _patch


def test_fresh_t86_passes(patch_today):
    patch_today({"tradingDate": "2026-07-03", "t86Date": "20260703",
                 "t86": {"2303": {"foreign": 35293}}})
    assert daily._fii_published() is True


def test_stale_t86_rejected(patch_today):
    # The actual 7/03 incident shape: t86 present but belongs to 7/02.
    patch_today({"tradingDate": "2026-07-03", "t86Date": "20260702",
                 "t86": {"2303": {"foreign": -12538}}})
    assert daily._fii_published() is False


def test_missing_t86_rejected(patch_today):
    patch_today({"tradingDate": "2026-07-03", "t86Date": None, "t86": {}})
    assert daily._fii_published() is False


def test_legacy_today_json_without_t86date_keeps_prior_behaviour(patch_today):
    # Pre-fix today.json has no t86Date → presence of t86 is enough (as before).
    patch_today({"tradingDate": "2026-07-03",
                 "t86": {"2303": {"foreign": 1}}})
    assert daily._fii_published() is True


def test_last_fetch_date_stamp():
    """fetch_twse_t86 records the yyyymmdd it actually requested."""
    import fetch_twse_t86 as t86

    # No network in tests: call with explicit date and a fetch that fails
    # immediately — LAST_FETCH_DATE must still be stamped before the request.
    t86.LAST_FETCH_DATE = None
    try:
        t86.fetch("20260703", retries=1, retry_sleep=0)
    except Exception:
        pass  # network blocked / unreachable — expected in CI sandbox
    assert t86.LAST_FETCH_DATE == "20260703"
