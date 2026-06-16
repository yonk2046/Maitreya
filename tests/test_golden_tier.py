"""Contract tests for core/golden.py tier + action metadata (T5).

Focuses on the pure tier-threshold mapping and the display/metadata maps.
action_group() branch coverage already lives in test_action_grouping.py, so
this file deliberately does not duplicate it — it locks _tier_from_score and
the consistency of the tier/action lookup tables instead.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import golden  # noqa: E402
from core.golden import (  # noqa: E402
    TIER_PRIME,
    TIER_STRONG,
    TIER_PRIME_KEY,
    TIER_STRONG_KEY,
    TIER_QUALIFIED_KEY,
    _tier_from_score,
)


# ── _tier_from_score ────────────────────────────────────────────────────────────

def test_tier_from_score_boundaries():
    assert _tier_from_score(1.0) == TIER_PRIME_KEY
    assert _tier_from_score(TIER_PRIME) == TIER_PRIME_KEY          # 0.65 inclusive
    assert _tier_from_score(TIER_PRIME - 0.01) == TIER_STRONG_KEY
    assert _tier_from_score(TIER_STRONG) == TIER_STRONG_KEY        # 0.40 inclusive
    assert _tier_from_score(TIER_STRONG - 0.01) == TIER_QUALIFIED_KEY
    assert _tier_from_score(0.0) == TIER_QUALIFIED_KEY


def test_tier_thresholds_ordered():
    assert 0.0 < TIER_STRONG < TIER_PRIME < 1.0


# ── tier display maps ────────────────────────────────────────────────────────────

def test_tier_keys_have_all_display_entries():
    keys = {TIER_PRIME_KEY, TIER_STRONG_KEY, TIER_QUALIFIED_KEY}
    assert set(golden.TIER_ZH) == keys
    assert set(golden.TIER_EN) == keys
    assert set(golden.TIER_COLOR) == keys
    assert set(golden.TIER_ICON) == keys


# ── action metadata ──────────────────────────────────────────────────────────────

def test_action_order_matches_meta_keys():
    assert set(golden.ACTION_ORDER) == set(golden.ACTION_META)
    # ACTION_ORDER must have no duplicates (used for sort priority)
    assert len(golden.ACTION_ORDER) == len(set(golden.ACTION_ORDER))


def test_action_meta_entries_complete():
    for code, meta in golden.ACTION_META.items():
        for key in ("icon", "zh", "en", "color"):
            assert key in meta, f"{code} missing {key}"
        assert meta["color"].startswith("#")
