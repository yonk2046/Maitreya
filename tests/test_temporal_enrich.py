"""Contract tests for core.market_context.temporal_enrich (P3b temporal layer).

Deterministic, replay-safe derivation of the time-series fields gates and the
paper-trading engine consume, built from the prior snapshot chain + today's
record. Tests craft small snapshot sequences and lock the outputs.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.market_context import temporal_enrich  # noqa: E402


def _snap(stocks):
    return {"stocks": stocks}


def _rec(t="2892", mf=None, vol=None, fii=None, chg=None):
    return {"ticker": t, "main_force_buy": mf, "volume": vol,
            "fii_net_buy": fii, "change_pct": chg}


def test_empty_prior_single_day():
    out = temporal_enrich("2892", [], _rec(mf=100, vol=1000, fii=50))
    assert out["main_force_consecutive_days"] == 1     # one positive day
    assert out["fii_consecutive_buy_days"] == 1
    assert out["volume_5d_avg"] == 1000.0
    assert out["volume_ratio"] == 1.0
    assert out["velocity_3d"] is None                  # need ≥2 obs
    assert out["volume_increasing_streak"] == 0


def test_main_force_consecutive_streak():
    priors = [
        _snap([_rec(mf=10)]),   # +
        _snap([_rec(mf=-5)]),   # − breaks
        _snap([_rec(mf=20)]),   # +
        _snap([_rec(mf=30)]),   # +
    ]
    out = temporal_enrich("2892", priors, _rec(mf=40))   # + (today)
    assert out["main_force_consecutive_days"] == 3       # 20,30,40 tail


def test_velocity_and_acceleration_present_with_enough_obs():
    priors = [_snap([_rec(mf=10)]), _snap([_rec(mf=20)]), _snap([_rec(mf=40)])]
    out = temporal_enrich("2892", priors, _rec(mf=80))   # 10,20,40,80
    assert out["velocity_3d"] is not None                # rising mf → positive
    assert out["velocity_3d"] > 0
    assert out["acceleration"] is not None


def test_volume_ratio_and_increasing_streak():
    priors = [_snap([_rec(vol=100)]), _snap([_rec(vol=150)]), _snap([_rec(vol=200)])]
    out = temporal_enrich("2892", priors, _rec(vol=300))   # 100,150,200,300
    # 5d avg over [100,150,200,300] = 187.5 ; ratio 300/187.5 = 1.6
    assert out["volume_5d_avg"] == 187.5
    assert out["volume_ratio"] == 1.6
    assert out["volume_increasing_streak"] == 3            # all rising at tail


def test_fii_streak_breaks_on_negative():
    priors = [_snap([_rec(fii=10)]), _snap([_rec(fii=-1)]), _snap([_rec(fii=5)])]
    out = temporal_enrich("2892", priors, _rec(fii=8))     # 10,-1,5,8
    assert out["fii_consecutive_buy_days"] == 2             # 5,8 tail


def test_deterministic_same_inputs_same_output():
    priors = [_snap([_rec(mf=10, vol=100, fii=5)]),
              _snap([_rec(mf=20, vol=120, fii=-3)])]
    today = _rec(mf=30, vol=150, fii=9)
    assert temporal_enrich("2892", priors, today) == temporal_enrich("2892", priors, today)


def test_ticker_isolation():
    # other tickers in the chain must not bleed into this ticker's series
    priors = [_snap([_rec("2892", mf=10), _rec("2330", mf=999)]),
              _snap([_rec("2892", mf=20), _rec("2330", mf=999)])]
    out = temporal_enrich("2892", priors, _rec("2892", mf=30))
    assert out["main_force_volume_trend"] == [10, 20, 30]   # only 2892's values
