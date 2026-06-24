"""Test the backtest HTML report generator (pure helpers + build)."""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools.render_backtest_report import _equity_curve, _histogram, build_html  # noqa: E402


def test_equity_curve_compounds_in_entry_order():
    trades = [
        {"entry_date": "2026-06-02", "return_pct": 0.10},
        {"entry_date": "2026-06-01", "return_pct": -0.05},
    ]
    eq = _equity_curve(trades)            # sorted by entry_date: -5% then +10%
    assert eq == [0.95, round(0.95 * 1.10, 4)]


def test_histogram_buckets():
    trades = [{"return_pct": r} for r in (-0.08, -0.02, 0.03, 0.07, 0.15, 0.30)]
    h = _histogram(trades)
    assert h["counts"] == [1, 1, 1, 1, 1, 1]
    assert len(h["labels"]) == 6


def test_build_html_embeds_data_and_is_selfcontained():
    strategies = [{
        "strategy": "momentum_continuation", "date_range": ["2026-05-08", "2026-06-24"],
        "summary": {"trades": 11, "win_rate": 0.727, "avg_return": 0.039,
                    "median_return": 0.026, "max_drawdown": -0.018,
                    "avg_holding_days": 4.18, "exit_reasons": {"end_of_data": 9}},
        "limitations": ["close-as-open proxy"],
        "trades": [{"ticker": "2330", "name": "台積電", "entry_date": "2026-06-10",
                    "exit_date": "2026-06-15", "return_pct": 0.05,
                    "exit_reason": "end_of_data", "holding_days": 3}],
    }]
    scans = [{"strategy": "momentum_continuation", "param": "entry_streak_min",
              "date_range": ["2026-05-08", "2026-06-24"],
              "rows": [{"value": 3, "trades": 11, "win_rate": 0.727, "avg_return": 0.039}]}]
    html = build_html(strategies, scans)
    assert "<!DOCTYPE html>" in html and "Maitreya 模擬績效報表" in html
    assert "momentum_continuation" in html and "台積電" in html
    assert "Chart.js" in html or "chart.umd" in html
    assert "/*DATA*/" not in html          # placeholder fully replaced
    assert "策略邏輯" in html and "進場" in html and "出場" in html   # logic embedded
