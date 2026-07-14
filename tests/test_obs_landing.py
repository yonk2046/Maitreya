"""P2-W3 per-ticker O 欄落地 — 驗收測試

涵蓋:
  • epoch-aware history_view(補充裁定 A / R4):三種 epoch 混合的 20 日窗
  • 雙軌一致性(本包靈魂):同一 window,落地欄 vs 引擎 render-time 路徑逐檔 diff 空
  • C10 bootstrap:1.9.0 首日 days_in_state == 1
  • obs_golden_near_miss 不含 tier(#26)
  • obs_dist_consistency #38:不在賣方榜→null
"""
from __future__ import annotations

import pytest

from core import history_view as hv
from core import state_machine as sm
from core import golden as golden_mod
from core import resonance as resonance_mod
from core import distribution as dist_mod
from core import chip_score as chip_mod
from core.ingest import ingest, SCHEMA_VERSION


# ── adapter_output / ingest helpers ───────────────────────────────────────────

def _raw(ticker, name, *, mfb, fii=None, cost=None, price=None, chg=None,
         sync=None, trust=None, prop=None, mkt_vol=None):
    """Minimal raw_inputs_per_ticker entry as _abstain_stock_record reads it."""
    return {
        "name":                 name,
        "current_price":        price,
        "change_pct":           chg,
        "total_buy_vol":        mfb,       # → main_force_buy
        "fii_net_buy":          fii,
        "fii_sync_count":       sync,
        "avg_buy_cost":         cost,      # → main_force_cost
        "market_volume":        mkt_vol,
        "investment_trust_net_buy": trust, # → dealer_net_buy (misnamed)
        "trust_net_buy":        trust,
        "prop_net_buy":         prop,
    }


def _ingest_day(date, raw_per_ticker, priors, *, sell_raw=None, obs_landing=True):
    universe = sorted(raw_per_ticker.keys())
    adapter_out = {
        "date":                  date,
        "raw_inputs_per_ticker": raw_per_ticker,
        "universe":              universe,
        "provenance_sources":    {},
        "audit_events":          [],
        "fii_pending":           False,
        "sell_raw":              sell_raw or {},
    }
    return ingest(adapter_out, {"meta": {"schema_version": SCHEMA_VERSION}},
                  prior_snapshots={p["date"]: "sha256:x" for p in priors},
                  prior_snap_objects=priors, obs_landing=obs_landing)


def _build_window(n_days, tickers, *, sell_raw_last=None):
    """Chain-ingest n_days so each day's priors are the prior landed snapshots.
    Returns the list of landed snapshots (oldest→newest)."""
    snaps: list[dict] = []
    for i in range(n_days):
        date = f"2026-06-{i + 1:02d}"
        raw = {}
        for t, (name, base_mfb, cost, price) in tickers.items():
            # steady accumulation: positive mfb each day, price drifting up
            raw[t] = _raw(t, name, mfb=base_mfb + i * 10, fii=base_mfb,
                          cost=cost, price=price + i * 0.5, chg=1.5,
                          sync=3, trust=base_mfb, prop=100, mkt_vol=50000)
        sr = sell_raw_last if i == n_days - 1 else None
        snap = _ingest_day(date, raw, list(snaps), sell_raw=sr)
        snaps.append(snap)
    return snaps


# ── 1. history_view: three-epoch mixed window (R4 fixture) ────────────────────

def test_history_view_epoch_classification():
    pre_obs  = {"schema_version": "1.8.1", "stocks": []}
    backfill = {"schema_version": "1.9.0", "obs_landing": False, "stocks": []}
    landed   = {"schema_version": "1.9.0", "obs_landing": True, "stocks": []}
    assert hv.snapshot_epoch(pre_obs) == hv.EPOCH_PRE_OBS
    assert hv.snapshot_epoch(backfill) == hv.EPOCH_BACKFILL
    assert hv.snapshot_epoch(landed) == hv.EPOCH_LANDED
    assert hv.has_landed_obs(landed) is True
    assert hv.has_landed_obs(pre_obs) is False
    assert hv.has_landed_obs(backfill) is False


def test_history_view_obs_absent_on_non_landed_epochs():
    t = "2330"
    pre_obs  = {"schema_version": "1.8.1", "stocks": [{"ticker": t}]}
    backfill = {"schema_version": "1.9.0", "obs_landing": False,
                "stocks": [{"ticker": t}]}  # I only, no obs_sm_state
    landed   = {"schema_version": "1.9.0", "obs_landing": True,
                "stocks": [{"ticker": t, "obs_sm_state": "confirmed"}]}
    assert hv.obs_sm_state(pre_obs, t) is hv.ABSENT
    assert hv.obs_sm_state(backfill, t) is hv.ABSENT
    assert hv.obs_sm_state(landed, t) == "confirmed"
    assert hv.obs_sm_state(landed, "9999") is hv.ABSENT   # ticker absent


def test_days_in_state_from_landed_mixed_window():
    """20 日混合 epoch 窗:只有 landed 且同 state 的尾段才累計。"""
    t = "2330"
    window: list[dict] = []
    # 8 days pre-obs (1.8.x) — ABSENT, must not count
    for i in range(8):
        window.append({"schema_version": "1.8.1", "date": f"2026-05-{i + 1:02d}",
                       "stocks": [{"ticker": t}]})
    # 4 days backfill — ABSENT, must not count
    for i in range(4):
        window.append({"schema_version": "1.9.0", "obs_landing": False,
                       "date": f"2026-05-{i + 20:02d}", "stocks": [{"ticker": t}]})
    # 3 landed days with state "confirmed"
    for i in range(3):
        window.append({"schema_version": "1.9.0", "obs_landing": True,
                       "date": f"2026-06-0{i + 1}",
                       "stocks": [{"ticker": t, "obs_sm_state": "confirmed"}]})
    days, entered = hv.days_in_state_from_landed(window, t, "confirmed", "2026-06-04")
    # 3 landed prior days + today = 4; entered = first of the 3 landed days
    assert days == 4
    assert entered == "2026-06-01"


def test_days_in_state_bootstrap_no_landed_priors():
    """C10 bootstrap: all priors pre-obs/backfill → days=1, entered=today."""
    t = "2330"
    priors = [{"schema_version": "1.8.1", "date": "2026-06-01",
               "stocks": [{"ticker": t}]}]
    days, entered = hv.days_in_state_from_landed(priors, t, "accumulating", "2026-06-02")
    assert days == 1
    assert entered == "2026-06-02"


# ── 2. Two-track consistency (本包靈魂) ───────────────────────────────────────

def _tickers():
    # (name, base_mfb, cost, price)
    return {
        "2330": ("台積電", 5000, 100.0, 105.0),
        "2454": ("聯發科", 3000, 200.0, 210.0),
        "1101": ("台泥",   -400, 40.0,  38.0),   # net seller
    }


def test_two_track_consistency_all_fields():
    snaps = _build_window(6, _tickers())
    last = snaps[-1]
    window = snaps  # ingest used prior landed snaps + provisional == this set (raw identical)

    # Independent render-time engine path
    sm_states = sm.run_all(window)
    gr = golden_mod.run(window, sm_states=sm_states)
    gate_passing = {e.ticker: e for e in (gr.prime + gr.strong + gr.qualified)}
    near_miss = {e.ticker: e for e in gr.near_miss}
    res = resonance_mod.run_all(window)

    for rec in last["stocks"]:
        t = rec["ticker"]
        ts = sm_states[t]
        # sm — pure raw-deterministic fields must be byte-equal to run_all
        assert rec["obs_sm_state"] == ts.state
        assert rec["obs_sm_transition_risk"] == ts.transition_risk
        assert rec["obs_sm_structure_unstable"] == bool(ts.structure_unstable)
        assert rec["obs_sm_risk_factors"] == list(ts.risk_factors)
        # days_in_state — landed-series discipline (recompute cross-check)
        exp_days, exp_entered = hv.days_in_state_from_landed(
            window[:-1], t, ts.state, last["date"])
        assert rec["obs_sm_days_in_state"] == exp_days
        assert rec["obs_sm_state_entered"] == exp_entered

        # golden — landed value must match the render-time golden result
        if t in gate_passing:
            e = gate_passing[t]
            assert rec["obs_golden_tier"] == e.tier
            assert rec["obs_golden_conviction"] == round(e.conviction, 4)
            assert rec["obs_golden_near_miss"] is None
        elif t in near_miss:
            assert rec["obs_golden_tier"] is None
            assert rec["obs_golden_near_miss"] is not None
            assert "tier" not in rec["obs_golden_near_miss"]   # #26
        else:
            assert rec["obs_golden_tier"] is None

        # chip — landed grade must match a fresh chip.compute over the same inputs
        cs = chip_mod.compute(
            streak=ts.streak, sponsorship=ts.sponsorship_score,
            fii_sync_count=rec.get("fii_sync_count"),
            main_force_buy=rec.get("main_force_buy"),
            market_volume=rec.get("market_volume"),
            main_force_cost=rec.get("main_force_cost"),
            current_price=rec.get("current_price"),
            top5_concentration=rec.get("top5_concentration"),
        )
        assert rec["obs_chip_grade"]["grade"] == cs.grade
        assert rec["obs_chip_grade"]["total"] == cs.total

        # sync_streak == resonance_streak (real cross-engine check)
        assert rec["sync_streak"] == res[t].resonance_streak


def test_bootstrap_first_day_days_in_state_is_one():
    """C10: 1.9.0 首日(無 landed 先驗)每檔 days_in_state == 1。"""
    snaps = _build_window(1, _tickers())
    first = snaps[0]
    for rec in first["stocks"]:
        assert rec["obs_sm_days_in_state"] == 1
        assert rec["obs_sm_state_entered"] == first["date"]


# ── 3. obs_dist_consistency #38: null unless on sell board ────────────────────

def test_obs_dist_consistency_null_when_not_on_sell_board():
    tickers = _tickers()
    # Put 1101 on the main-force sell board; 2330/2454 stay off any sell board.
    sell_raw = {
        "fii_sell_raw":        [],
        "main_force_sell_raw": [{"code": "1101", "rank": 1, "sellVol": 9000, "name": "台泥"}],
        "buy_list":            [],
        "main_force_buy_raw":  [{"code": "2330", "rank": 1, "buyVol": 9000, "name": "台積電"}],
    }
    snaps = _build_window(3, tickers, sell_raw_last=sell_raw)
    last = snaps[-1]
    by = {r["ticker"]: r for r in last["stocks"]}
    assert by["1101"]["obs_dist_consistency"] is not None
    assert by["1101"]["obs_dist_consistency"]["main_status"] == "sell"
    # 2330/2454 not on any sell board → null (唯一賣方證據源)
    assert by["2330"]["obs_dist_consistency"] is None
    assert by["2454"]["obs_dist_consistency"] is None


def test_backfill_mode_writes_no_obs_fields():
    """obs_landing=False → 只 I 欄、跳過全部 O(D-7)。"""
    snap = _ingest_day("2026-06-01", {"2330": _raw("2330", "台積電", mfb=5000,
                       trust=5000, prop=100)}, [], obs_landing=False)
    rec = snap["stocks"][0]
    assert snap["obs_landing"] is False
    assert "trust_net_buy" in rec           # I field still landed
    for f in ("obs_sm_state", "obs_golden_tier", "obs_chip_grade",
              "obs_dist_consistency", "sync_streak"):
        assert f not in rec                 # no O fields
