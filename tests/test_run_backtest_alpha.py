"""tools/run_backtest.py — R4 benchmark/alpha enrichment. Wave A3 (2026-07-23).

Covers `_enrich_with_benchmark`: per-trade benchmark_return_pct/excess_return_pct
and the aggregate alpha summary, using a small synthetic taiex_history (not the
real file) so the assertions are independent of live data drift.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools.run_backtest import _enrich_with_benchmark  # noqa: E402

HISTORY = {
    "2026-05-08": {"close": 100.0},
    "2026-05-11": {"close": 110.0},   # +10% over the full window
    "2026-05-12": {"close": 105.0},
}


def _payload(trades):
    return {"date_range": ["2026-05-08", "2026-05-12"], "trades": trades, "summary": {}}


def test_per_trade_excess_return_computed():
    payload = _payload([
        {"entry_date": "2026-05-08", "exit_date": "2026-05-11", "return_pct": 0.20},
    ])
    _enrich_with_benchmark(payload, HISTORY)
    t = payload["trades"][0]
    assert t["benchmark_return_pct"] == 0.1
    assert t["excess_return_pct"] == round(0.20 - 0.1, 4)


def test_missing_benchmark_date_yields_none_not_crash():
    payload = _payload([
        {"entry_date": "2024-01-01", "exit_date": "2024-01-02", "return_pct": 0.05},
    ])
    _enrich_with_benchmark(payload, HISTORY)
    t = payload["trades"][0]
    assert t["benchmark_return_pct"] is None
    assert t["excess_return_pct"] is None


def test_alpha_summary_aggregates_only_resolvable_trades():
    payload = _payload([
        {"entry_date": "2026-05-08", "exit_date": "2026-05-11", "return_pct": 0.20},  # excess +0.10
        {"entry_date": "2026-05-08", "exit_date": "2026-05-12", "return_pct": 0.10},  # bench +0.05, excess +0.05
        {"entry_date": "1999-01-01", "exit_date": "1999-01-02", "return_pct": 0.99},  # unresolvable
    ])
    _enrich_with_benchmark(payload, HISTORY)
    alpha = payload["summary"]["alpha"]
    assert alpha["trades_total"] == 3
    assert alpha["trades_with_benchmark"] == 2
    assert alpha["avg_excess_return"] == round((0.10 + 0.05) / 2, 4)
    assert alpha["period_buy_hold_return"] == round((105.0 - 100.0) / 100.0, 4)


def test_empty_trades_no_crash():
    payload = _payload([])
    _enrich_with_benchmark(payload, HISTORY)
    alpha = payload["summary"]["alpha"]
    assert alpha["trades_total"] == 0
    assert alpha["avg_excess_return"] is None


def test_no_history_all_fields_none():
    payload = _payload([
        {"entry_date": "2026-05-08", "exit_date": "2026-05-11", "return_pct": 0.20},
    ])
    _enrich_with_benchmark(payload, {})
    t = payload["trades"][0]
    assert t["benchmark_return_pct"] is None
    assert payload["summary"]["alpha"]["avg_excess_return"] is None
