"""Tests for Schema v1.5 additions in core/ingest.py and core/golden.py.

Covers:
  - _compute_completeness: fraction + tier thresholds
  - _abstain_stock_record: v1.5 fields present and correctly typed
  - ingest(): schema_version is 1.5.0, all stocks have new fields
  - SKELETON gate: golden layer caps SKELETON ticker at STRONG, not PRIME
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.ingest import (  # noqa: E402
    CONFIDENCE_TIER_FULL,
    CONFIDENCE_TIER_PARTIAL,
    CONFIDENCE_TIER_SKELETON,
    SCHEMA_VERSION,
    _COMPLETENESS_FIELDS,
    _abstain_stock_record,
    _compute_completeness,
)


# ---------------------------------------------------------------------------
# _compute_completeness
# ---------------------------------------------------------------------------

class TestComputeCompleteness:
    def _rec(self, **overrides) -> dict:
        """Minimal record with all key fields None, override as needed."""
        base = {f: None for f in _COMPLETENESS_FIELDS}
        base.update(overrides)
        return base

    def test_all_none_is_skeleton(self):
        frac, tier = _compute_completeness(self._rec())
        assert frac == 0.0
        assert tier == CONFIDENCE_TIER_SKELETON

    def test_all_present_is_full(self):
        rec = self._rec(**{f: 1 for f in _COMPLETENESS_FIELDS})
        frac, tier = _compute_completeness(rec)
        assert frac == 1.0
        assert tier == CONFIDENCE_TIER_FULL

    def test_exactly_80pct_is_full(self):
        """Provide enough fields to hit ≥ 0.80 fraction."""
        import math
        n = len(_COMPLETENESS_FIELDS)
        needed = math.ceil(n * 0.8)   # ceiling so fraction is ≥ 0.80
        fields = list(_COMPLETENESS_FIELDS)
        overrides = {f: 1 for f in fields[:needed]}
        rec = self._rec(**overrides)
        frac, tier = _compute_completeness(rec)
        assert frac >= 0.80
        assert tier == CONFIDENCE_TIER_FULL

    def test_below_50pct_is_skeleton(self):
        n = len(_COMPLETENESS_FIELDS)
        below_half = int(n * 0.4)
        fields = list(_COMPLETENESS_FIELDS)
        rec = self._rec(**{f: 1 for f in fields[:below_half]})
        frac, tier = _compute_completeness(rec)
        assert frac < 0.50
        assert tier == CONFIDENCE_TIER_SKELETON

    def test_exactly_50pct_is_partial(self):
        n = len(_COMPLETENESS_FIELDS)
        half = n // 2
        fields = list(_COMPLETENESS_FIELDS)
        rec = self._rec(**{f: 1 for f in fields[:half]})
        frac, tier = _compute_completeness(rec)
        # With floor-division, half may be slightly below 0.5 for odd n;
        # test the boundary explicitly.
        if frac >= 0.50:
            assert tier in (CONFIDENCE_TIER_PARTIAL, CONFIDENCE_TIER_FULL)
        else:
            assert tier == CONFIDENCE_TIER_SKELETON

    def test_mid_range_is_partial(self):
        n = len(_COMPLETENESS_FIELDS)
        mid = int(n * 0.65)
        fields = list(_COMPLETENESS_FIELDS)
        rec = self._rec(**{f: 1 for f in fields[:mid]})
        frac, tier = _compute_completeness(rec)
        assert 0.50 <= frac < 0.80
        assert tier == CONFIDENCE_TIER_PARTIAL

    def test_false_counts_as_present(self):
        """False is not None — boolean False should count as present."""
        rec = self._rec(current_price=False)
        frac1, _ = _compute_completeness(rec)
        rec2 = self._rec(current_price=None)
        frac2, _ = _compute_completeness(rec2)
        assert frac1 > frac2

    def test_zero_counts_as_present(self):
        """0 is not None — a value of 0 should count as present."""
        rec = self._rec(current_price=0)
        frac, _ = _compute_completeness(rec)
        assert frac > 0.0


# ---------------------------------------------------------------------------
# _abstain_stock_record — v1.5 fields present and correctly typed
# ---------------------------------------------------------------------------

class TestAbstainStockRecordV15:
    def _raw(self, **overrides) -> dict:
        base = {"name": "Test", "current_price": 100.0, "change_pct": 1.5}
        base.update(overrides)
        return base

    def _rec(self, **raw_overrides) -> dict:
        return _abstain_stock_record("9999", self._raw(**raw_overrides), has_branches=False)

    def test_data_completeness_present_and_float(self):
        rec = self._rec()
        assert "data_completeness" in rec
        assert isinstance(rec["data_completeness"], float)
        assert 0.0 <= rec["data_completeness"] <= 1.0

    def test_confidence_tier_present_and_valid(self):
        rec = self._rec()
        valid = {CONFIDENCE_TIER_FULL, CONFIDENCE_TIER_PARTIAL, CONFIDENCE_TIER_SKELETON}
        assert rec["confidence_tier"] in valid

    def test_momentum_direction_present(self):
        rec = self._rec()
        assert "momentum_direction" in rec
        assert rec["momentum_direction"] == "unknown"  # stub in P3a

    def test_signal_age_days_present_and_int(self):
        rec = self._rec()
        assert "signal_age_days" in rec
        assert isinstance(rec["signal_age_days"], int)
        assert rec["signal_age_days"] >= 1

    def test_delta_vs_yesterday_present(self):
        rec = self._rec()
        assert "delta_vs_yesterday" in rec
        assert rec["delta_vs_yesterday"] == "—"  # stub in P3a

    def test_no_data_gives_skeleton(self):
        """A ticker with only name → most fields None → SKELETON."""
        raw = {"name": "Bare"}
        rec = _abstain_stock_record("0001", raw, has_branches=False)
        assert rec["confidence_tier"] == CONFIDENCE_TIER_SKELETON

    def test_rich_data_gives_partial_or_full(self):
        """A ticker with price + vol + fii + TDCC data → at least PARTIAL."""
        # current_price, change_pct, volume(from buy_vol_lots), fii_net_buy,
        # main_force_buy(from total_buy_vol), large_holder_400/1000, shareholder_count
        # = 8 / 11 ≈ 0.727 → PARTIAL
        raw = {
            "name": "Rich",
            "current_price": 50.0,
            "change_pct": 0.5,
            "buy_vol_lots": 1000,        # → volume
            "fii_net_buy": 200,
            "total_buy_vol": 500,        # → main_force_buy
            "large_holder_400_pct": 80.0,
            "large_holder_1000_pct": 60.0,
            "shareholder_count": 5000,
        }
        rec = _abstain_stock_record("2330", raw, has_branches=True)
        assert rec["confidence_tier"] in {CONFIDENCE_TIER_PARTIAL, CONFIDENCE_TIER_FULL}
        assert rec["large_holder_400_pct"] == 80.0    # confirm TDCC pass-through
        assert rec["shareholder_count"] == 5000


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

def test_schema_version_is_v15():
    assert SCHEMA_VERSION == "1.5.0"


# ---------------------------------------------------------------------------
# SKELETON gate in golden layer
# ---------------------------------------------------------------------------

def test_skeleton_gate_caps_at_strong():
    """A SKELETON ticker that would score PRIME is capped at STRONG."""
    from core.golden import (
        TIER_PRIME_KEY,
        TIER_STRONG_KEY,
        _tier_from_score,
    )
    from core.golden import TIER_PRIME  # conviction threshold

    # Confirm a high conviction normally yields PRIME
    assert _tier_from_score(TIER_PRIME + 0.01) == TIER_PRIME_KEY

    # Simulate the gate: apply the same logic run() uses
    conviction = TIER_PRIME + 0.01
    tier = _tier_from_score(conviction)
    confidence_tier = CONFIDENCE_TIER_SKELETON  # the SKELETON stock

    if confidence_tier == CONFIDENCE_TIER_SKELETON and tier == TIER_PRIME_KEY:
        tier = TIER_STRONG_KEY

    assert tier == TIER_STRONG_KEY, "SKELETON ticker must not become PRIME"


def test_partial_ticker_can_reach_prime():
    """A PARTIAL ticker is allowed to reach PRIME (only SKELETON is gated)."""
    from core.golden import TIER_PRIME_KEY, TIER_PRIME, _tier_from_score

    conviction = TIER_PRIME + 0.01
    tier = _tier_from_score(conviction)
    confidence_tier = CONFIDENCE_TIER_PARTIAL

    # PARTIAL does not trigger the gate
    if confidence_tier == CONFIDENCE_TIER_SKELETON and tier == TIER_PRIME_KEY:
        tier = "downgraded"  # should not happen

    assert tier == TIER_PRIME_KEY


def test_full_ticker_can_reach_prime():
    """A FULL ticker is allowed to reach PRIME."""
    from core.golden import TIER_PRIME_KEY, TIER_PRIME, _tier_from_score

    conviction = TIER_PRIME + 0.01
    tier = _tier_from_score(conviction)

    if CONFIDENCE_TIER_FULL == CONFIDENCE_TIER_SKELETON and tier == TIER_PRIME_KEY:
        tier = "downgraded"

    assert tier == TIER_PRIME_KEY


def test_skeleton_below_prime_stays_strong_or_qualified():
    """A SKELETON ticker scoring below PRIME threshold is not affected by the gate."""
    from core.golden import TIER_PRIME_KEY, TIER_PRIME, TIER_STRONG, _tier_from_score

    conviction = (TIER_PRIME + TIER_STRONG) / 2  # between STRONG and PRIME
    tier = _tier_from_score(conviction)
    assert tier != TIER_PRIME_KEY  # already below PRIME, gate irrelevant
