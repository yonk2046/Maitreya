"""Contract tests for core/confidence.py pure banding helpers (T5).

Covers the deterministic, I/O-free parts: confidence band thresholds,
profile-code derivation, and display-map key consistency. The full run()
path depends on snapshot data and is exercised elsewhere; here we lock the
small pure functions that decide how a score becomes a label.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import confidence  # noqa: E402
from core.confidence import (  # noqa: E402
    CONF_HIGH,
    CONF_MID,
    _confidence_band,
    _profile_code,
)


# ── _confidence_band ───────────────────────────────────────────────────────────

def test_confidence_band_boundaries():
    assert _confidence_band(1.0) == "high"
    assert _confidence_band(CONF_HIGH) == "high"          # 0.55 inclusive
    assert _confidence_band(CONF_HIGH - 0.01) == "mid"
    assert _confidence_band(CONF_MID) == "mid"            # 0.30 inclusive
    assert _confidence_band(CONF_MID - 0.01) == "low"
    assert _confidence_band(0.0) == "low"


def test_conf_thresholds_ordered():
    assert 0.0 < CONF_MID < CONF_HIGH < 1.0


# ── _profile_code ──────────────────────────────────────────────────────────────

def test_profile_code_deteriorating_overrides_everything():
    assert _profile_code("high", "low", deteriorating=True) == "deteriorating"
    assert _profile_code("low", "critical", deteriorating=True) == "deteriorating"


def test_profile_code_low_band_is_insufficient_signal():
    assert _profile_code("low", "low", deteriorating=False) == "low_any"
    assert _profile_code("low", "elevated", deteriorating=False) == "low_any"


def test_profile_code_band_x_risk_matrix():
    assert _profile_code("high", "low", False) == "high_low"
    assert _profile_code("high", "medium", False) == "high_medium"
    assert _profile_code("high", "elevated", False) == "high_elevated"
    # critical collapses to elevated for profile purposes
    assert _profile_code("high", "critical", False) == "high_elevated"
    assert _profile_code("mid", "low", False) == "mid_low"
    assert _profile_code("mid", "medium", False) == "mid_medium"
    assert _profile_code("mid", "critical", False) == "mid_elevated"


# ── display-map consistency ─────────────────────────────────────────────────────

def test_profile_display_maps_share_keys():
    keys_zh = set(confidence.PROFILE_ZH)
    assert set(confidence.PROFILE_EN) == keys_zh
    assert set(confidence.PROFILE_COLOR) == keys_zh


def test_every_producible_profile_code_has_display_entries():
    produced = set()
    produced.add(_profile_code("high", "low", True))   # deteriorating
    for band in ("high", "mid", "low"):
        for risk in ("low", "medium", "elevated", "critical"):
            produced.add(_profile_code(band, risk, False))
    for code in produced:
        assert code in confidence.PROFILE_ZH
        assert code in confidence.PROFILE_EN
        assert code in confidence.PROFILE_COLOR
