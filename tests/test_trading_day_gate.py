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

from tools.daily import _trading_day_gate  # noqa: E402


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
