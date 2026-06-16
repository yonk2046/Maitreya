"""Contract tests for core/resonance.py (T5 — 三方共振 detection).

Pure functions over snapshot dicts: participant sign detection, per-stock
resonance level/streak/strength, and the run_all/run_one public API.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import resonance  # noqa: E402
from core.resonance import _participant_sign, run_all, run_one  # noqa: E402


def _stock(ticker="2892", mf=None, fii=None, dealer=None):
    return {
        "ticker": ticker,
        "main_force_buy": mf,
        "fii_net_buy": fii,
        "dealer_net_buy": dealer,
    }


def _snap(stocks):
    return {"stocks": stocks}


# ── _participant_sign ──────────────────────────────────────────────────────────

def test_participant_sign_tristate():
    assert _participant_sign({"x": 100}, "x") is True
    assert _participant_sign({"x": 0}, "x") is False    # zero is not positive
    assert _participant_sign({"x": -5}, "x") is False
    assert _participant_sign({"x": None}, "x") is None
    assert _participant_sign({}, "x") is None            # missing key → None


# ── levels / labels ────────────────────────────────────────────────────────────

def test_empty_snapshots_is_no_resonance():
    r = run_one("2892", [])
    assert r.resonance_level == 0
    assert r.resonance_label_zh == "無共振"
    assert r.resonance_strength == 0
    assert r.resonance_streak == 0


def test_triple_resonance_single_day():
    snaps = [_snap([_stock("2892", mf=100, fii=50, dealer=20)])]
    r = run_one("2892", snaps)
    assert r.resonance_level == 3
    assert r.resonance_label_zh == "三方共振"
    assert set(r.resonance_members) == {"main_force", "foreign", "invest_trust"}
    assert r.resonance_streak == 1                 # level 3 >= 2 for the one day
    # strength = level*25 + min(streak*5, 25) = 75 + 5
    assert r.resonance_strength == 80
    assert r.stars == "★★★"


def test_single_party_with_missing_data():
    # main_force positive, foreign missing (None), dealer negative
    snaps = [_snap([_stock("2892", mf=100, fii=None, dealer=-5)])]
    r = run_one("2892", snaps)
    assert r.resonance_level == 1
    assert r.resonance_label_zh == "單方買盤"
    assert r.resonance_members == ["main_force"]
    assert r.participant_status["foreign"] is None
    assert r.participant_status["invest_trust"] is False
    assert r.resonance_streak == 0                 # level 1 < 2
    assert r.resonance_strength == 25              # 1*25 + 0


def test_streak_counts_consecutive_ge2_from_latest():
    snaps = [
        _snap([_stock("2892", mf=10, fii=10, dealer=-1)]),   # level 2
        _snap([_stock("2892", mf=10, fii=10, dealer=-1)]),   # level 2
        _snap([_stock("2892", mf=10, fii=10, dealer=10)]),   # level 3 (latest)
    ]
    r = run_one("2892", snaps)
    assert r.resonance_level == 3
    assert r.resonance_streak == 3
    # strength = 3*25 + min(3*5, 25) = 75 + 15 = 90
    assert r.resonance_strength == 90


def test_streak_breaks_on_low_day():
    snaps = [
        _snap([_stock("2892", mf=10, fii=10, dealer=10)]),   # level 3
        _snap([_stock("2892", mf=10, fii=-1, dealer=-1)]),   # level 1 (breaks)
        _snap([_stock("2892", mf=10, fii=10, dealer=10)]),   # level 3 (latest)
    ]
    r = run_one("2892", snaps)
    assert r.resonance_streak == 1                 # only the latest day
    assert r.resonance_strength == 80              # 75 + 5


# ── run_all public API ──────────────────────────────────────────────────────────

def test_run_all_keys_come_from_latest_snapshot_only():
    snaps = [
        _snap([_stock("1111", mf=1, fii=1, dealer=1)]),       # only in older snap
        _snap([_stock("2892", mf=1), _stock("2330", mf=1)]),  # latest
    ]
    result = run_all(snaps)
    assert set(result.keys()) == {"2892", "2330"}
    assert "1111" not in result


def test_run_all_empty_is_empty_dict():
    assert run_all([]) == {}


def test_level_labels_cover_all_levels():
    # Guard the label map against accidental gaps.
    assert set(resonance._LEVEL_LABELS.keys()) == {0, 1, 2, 3}
