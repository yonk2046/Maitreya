"""P0.7 — FII alignment hard gate tests (外資同向 PRIME 硬閘門).

SCD 雙引擎 V3 charter: 外資與主力同向 is a NECESSARY condition for PRIME.
fii_net_buy < 0 for ≥ contra_days_cap consecutive snapshots caps tier at
STRONG. None/absence breaks the streak (no data ≠ sell evidence).
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import golden  # noqa: E402


def _snaps(fii_series, ticker="9999"):
    out = []
    for i, fii in enumerate(fii_series):
        out.append({
            "date": f"2026-06-{i+1:02d}",
            "stocks": [{"ticker": ticker, "fii_net_buy": fii,
                        "main_force_buy": 1000}],
        })
    return out


# ----------------------------------------------------------------------
# _fii_contra_streak
# ----------------------------------------------------------------------

def test_contra_streak_counts_trailing_negatives():
    assert golden._fii_contra_streak("9999", _snaps([100, -50, -80])) == 2


def test_contra_streak_zero_when_latest_positive():
    assert golden._fii_contra_streak("9999", _snaps([-50, -80, 100])) == 0


def test_none_breaks_streak():
    # None = no data, must NOT count as selling
    assert golden._fii_contra_streak("9999", _snaps([-50, None, -80])) == 1
    assert golden._fii_contra_streak("9999", _snaps([-50, -80, None])) == 0


def test_absence_breaks_streak():
    snaps = _snaps([-50, -80])
    snaps.append({"date": "2026-06-03", "stocks": []})  # ticker absent latest
    assert golden._fii_contra_streak("9999", snaps) == 0


# ----------------------------------------------------------------------
# _apply_tier_caps
# ----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_cfg():
    golden._reset_fii_alignment_cfg()
    yield
    golden._reset_fii_alignment_cfg()


def test_prime_capped_on_contra_2d():
    tier, reasons = golden._apply_tier_caps(golden.TIER_PRIME_KEY, {}, fii_contra=2)
    assert tier == golden.TIER_STRONG_KEY
    assert any(r.startswith("CAP_fii_contra") for r in reasons)


def test_prime_kept_on_contra_1d():
    tier, reasons = golden._apply_tier_caps(golden.TIER_PRIME_KEY, {}, fii_contra=1)
    assert tier == golden.TIER_PRIME_KEY
    assert reasons == []


def test_strong_not_affected():
    tier, reasons = golden._apply_tier_caps(golden.TIER_STRONG_KEY, {}, fii_contra=5)
    assert tier == golden.TIER_STRONG_KEY
    assert reasons == []


def test_skeleton_cap_still_applies():
    tier, reasons = golden._apply_tier_caps(
        golden.TIER_PRIME_KEY, {"confidence_tier": "SKELETON"}, fii_contra=0)
    assert tier == golden.TIER_STRONG_KEY
    assert "CAP_skeleton_data" in reasons


def test_both_caps_record_skeleton_first():
    # SKELETON fires first and already caps to STRONG; FII cap then no-ops
    tier, reasons = golden._apply_tier_caps(
        golden.TIER_PRIME_KEY, {"confidence_tier": "SKELETON"}, fii_contra=3)
    assert tier == golden.TIER_STRONG_KEY
    assert reasons == ["CAP_skeleton_data"]


def test_gate_disabled_via_cfg(monkeypatch):
    monkeypatch.setattr(golden, "_FII_ALIGNMENT_CFG",
                        {"enabled": False, "contra_days_cap": 2})
    tier, reasons = golden._apply_tier_caps(golden.TIER_PRIME_KEY, {}, fii_contra=9)
    assert tier == golden.TIER_PRIME_KEY
    assert reasons == []


def test_cfg_loads_from_example_yaml():
    cfg = golden._fii_alignment_cfg()
    assert cfg["enabled"] is True
    assert cfg["contra_days_cap"] == 2
