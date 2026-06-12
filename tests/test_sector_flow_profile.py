"""P4 — sector flow profile tests (板塊輪動強化聚合層).

Validates per-sector aggregation of mfb flow, lifecycle states, weakening
severities, and the W3-concentration rotation-out alert.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import sector_intelligence as si  # noqa: E402


# Curated sector members (stable regardless of industry cache)
_FIN = ["2881", "2882", "2891", "2884"]      # financials
_SEMI = ["2330", "2454"]                      # semiconductor


def _snap(date, rows):
    """rows: {ticker: mfb or None-for-absent}"""
    stocks = []
    for t, mfb in rows.items():
        if mfb is None:
            continue
        stocks.append({"ticker": t, "name": t, "main_force_buy": mfb,
                       "current_price": 100.0, "volume": 1000, "change_pct": 0.1})
    return {"date": date, "stocks": stocks}


def _cluster_w3_snaps():
    """4 financials accumulate ≥3 days then ALL vanish; semis keep buying."""
    snaps = []
    for i in range(4):  # 4 days of accumulation
        rows = {t: 2000 + i * 100 for t in _FIN}
        rows.update({t: 3000 for t in _SEMI})
        snaps.append(_snap(f"2026-06-{i+1:02d}", rows))
    for i in range(2):  # financials vanish (within W3 recency gate ≤3)
        rows = {t: None for t in _FIN}
        rows.update({t: 3000 for t in _SEMI})
        snaps.append(_snap(f"2026-06-{i+5:02d}", rows))
    return snaps


def test_rotation_out_alert_fires_for_cluster_w3():
    prof = si.sector_flow_profile(_cluster_w3_snaps())
    fin = next(s for s in prof["sectors"] if s["sector"] == "financials")
    assert set(fin["w3_tickers"]) == set(_FIN)
    assert fin["w3_concentration"] == 1.0
    assert fin["rotation_out_alert"] is True
    assert any(a["sector"] == "financials" and a["type"] == "rotation_out"
               for a in prof["alerts"])


def test_healthy_sector_no_alert():
    prof = si.sector_flow_profile(_cluster_w3_snaps())
    semi = next(s for s in prof["sectors"] if s["sector"] == "semiconductor")
    assert semi["w3_tickers"] == []
    assert semi["rotation_out_alert"] is False
    # semis still buying → top of net_mfb_latest ranking
    assert prof["sectors"][0]["sector"] == "semiconductor"


def test_two_w3_below_min_threshold_no_alert():
    # Only 2 of 4 financials vanish → below _W3_ALERT_MIN_TICKERS(3)
    snaps = []
    for i in range(4):
        rows = {t: 2000 for t in _FIN}
        rows.update({t: 3000 for t in _SEMI})
        snaps.append(_snap(f"2026-06-{i+1:02d}", rows))
    rows = {"2881": None, "2882": None, "2891": 2000, "2884": 2000}
    rows.update({t: 3000 for t in _SEMI})
    snaps.append(_snap("2026-06-05", rows))
    prof = si.sector_flow_profile(snaps)
    fin = next(s for s in prof["sectors"] if s["sector"] == "financials")
    assert len(fin["w3_tickers"]) == 2
    assert fin["rotation_out_alert"] is False


def test_net_mfb_sums():
    snaps = _cluster_w3_snaps()
    prof = si.sector_flow_profile(snaps)
    semi = next(s for s in prof["sectors"] if s["sector"] == "semiconductor")
    assert semi["net_mfb_latest"] == 6000          # 2 tickers × 3000
    assert semi["net_mfb_3d"] == 18000             # 3 snaps × 6000
    fin = next(s for s in prof["sectors"] if s["sector"] == "financials")
    assert fin["net_mfb_latest"] == 0              # all absent latest


def test_empty_input():
    prof = si.sector_flow_profile([])
    assert prof["sectors"] == [] and prof["alerts"] == []


def test_real_snapshots_smoke():
    """Integration on real reports/ data — and the 6/10 financials W3
    cluster from the handoff should be visible in the window ending 6/10."""
    import json
    reports = sorted((_AI_STOCK / "reports").glob("2026-*.json"))
    snaps = []
    for f in reports:
        if f.name.endswith(".intelligence.json") or "example" in f.name:
            continue
        s = json.loads(f.read_text(encoding="utf-8"))
        if s.get("stocks"):
            snaps.append(s)
    if len(snaps) < 5:
        pytest.skip("not enough real snapshots")
    upto_610 = [s for s in snaps if s["date"] <= "2026-06-10"]
    prof = si.sector_flow_profile(upto_610)
    assert prof["sectors"]
    fin = next((s for s in prof["sectors"] if s["sector"] == "financials"), None)
    assert fin is not None
    # the handoff observed a financials W3 cluster on 6/10
    assert len(fin["w3_tickers"]) >= 2
