"""Tests for tools.daily._trading_day_gate (holiday / staleness disposition).

Pure ISO-date comparison: decides whether the auto-daily path should fail
(regression), skip cleanly (no new trading session — holiday/weekend), or
proceed (genuine new session).
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import tools.daily as _daily  # noqa: E402
from tools.daily import _trading_day_gate  # noqa: E402


def test_fii_published_gate(tmp_path, monkeypatch):
    f = tmp_path / "today.json"
    monkeypatch.setattr(_daily, "TODAY_JSON", f)
    assert _daily._fii_published() is False                         # no file
    f.write_text('{"t86": {}}', encoding="utf-8")
    assert _daily._fii_published() is False                         # empty t86 (intraday)
    f.write_text('{"t86": {"2330": {"foreign": 100}}}', encoding="utf-8")
    assert _daily._fii_published() is True                          # T86 present (post-close)


def test_regression_fails():
    # fetch returned an older date than what we already committed
    assert _trading_day_gate("2026-06-11", "2026-06-12") == "fail"


def test_no_new_session_skips():
    # holiday / weekend / pre-publish: resolved date already committed
    assert _trading_day_gate("2026-06-18", "2026-06-18") == "skip"


def test_new_session_proceeds():
    assert _trading_day_gate("2026-06-19", "2026-06-18") == "proceed"


def test_empty_archive_proceeds():
    # bootstrap: nothing committed yet
    assert _trading_day_gate("2026-06-19", None) == "proceed"
