"""守門員:A6 回測撮合價與掉榜持倉(PLAN-yearly-backtest B1/B3)。

B1 撮合價:快照的 `open` 在 2026-09-23 前 95% 是前一交易日的 → 改讀
   `data/prices/<date>.json`(TWSE MI_INDEX 按日期,全市場)。
B3 掉榜凍結:持倉一離開主力買超榜,舊引擎 `continue` —— 不更新峰值、不檢查停損、
   不能出場(實測持有日的 53%)。改為用價格檔逐日估值,籌碼證據連 N 日消失才出場。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import prices as _prices, paper_trading as pt  # noqa: E402
from core.engine_params import BACKTEST_OFFLIST_EXIT_DAYS  # noqa: E402
from core.strategies import ALL_STRATEGIES  # noqa: E402


@pytest.fixture()
def px(tmp_path, monkeypatch):
    monkeypatch.setattr(_prices, "PRICES_DIR", tmp_path)
    _prices._cache.clear()
    yield tmp_path
    _prices._cache.clear()


def test_fill_price_prefers_the_session_price_file(px):
    _prices.write_day("2026-09-23", {"2330": {"o": 100.0, "c": 105.0}}, base_dir=px)
    snap = {"date": "2026-09-23", "stocks": [{"ticker": "2330", "open": 88.0, "current_price": 105.0}]}
    assert pt._fill_price(snap, "2330") == 100.0          # 檔案的真開盤,不是快照的 88(前一日)
    assert pt._mark_price(snap, "2330") == 105.0


def test_fill_and_mark_work_for_a_ticker_absent_from_the_snapshot(px):
    _prices.write_day("2026-09-23", {"2330": {"o": 100.0, "c": 96.0}}, base_dir=px)
    snap = {"date": "2026-09-23", "stocks": []}           # 掉出主力買超榜
    assert pt._fill_price(snap, "2330") == 100.0
    assert pt._mark_price(snap, "2330") == 96.0


def test_falls_back_to_snapshot_when_no_price_file(px):
    snap = {"date": "2026-09-23", "stocks": [{"ticker": "2330", "open": 88.0, "current_price": 90.0}]}
    assert pt._fill_price(snap, "2330") == 88.0
    assert pt._mark_price(snap, "2330") == 90.0
    assert pt._fill_price({"date": "2026-09-23", "stocks": []}, "2330") is None


def test_prices_are_worm(px):
    assert _prices.write_day("2026-09-23", {"2330": {"c": 1.0}}, base_dir=px) is True
    assert _prices.write_day("2026-09-23", {"2330": {"c": 1.0}}, base_dir=px) is False
    with pytest.raises(ValueError):
        _prices.write_day("2026-09-23", {"2330": {"c": 2.0}}, base_dir=px)


def _corpus():
    idx = json.loads((_ROOT / "reports" / "index.json").read_text())["snapshots"]
    ds = sorted(d for d, e in idx.items() if "example" not in d and "example" not in e["current"])
    return ds, [json.loads((_ROOT / "reports" / idx[d]["current"]).read_text()) for d in ds]


@pytest.mark.slow
def test_no_position_is_frozen_off_the_list():
    """B3 回歸:任何一筆交易的持有期內,連續掉榜天數不得超過設定值(+1 個成交日)。"""
    ds, snaps = _corpus()
    present = {d: {s["ticker"] for s in snap["stocks"]} for d, snap in zip(ds, snaps)}
    worst = 0
    for name in ("chip_anchored_swing", "chip_anchored_v3"):
        for t in pt.run_backtest(snaps, ALL_STRATEGIES[name]).trades:
            run = 0
            for d in [x for x in ds if t.entry_date <= x < t.exit_date]:
                run = 0 if t.ticker in present[d] else run + 1
                worst = max(worst, run)
    assert worst <= BACKTEST_OFFLIST_EXIT_DAYS + 1, f"最長連續掉榜持有 {worst} 日"
