"""守門員:A5② 個股融資(TWSE MI_MARGN?date=&selectType=ALL)。

`margin_balance`/`margin_change` 在此之前是寫死的 None(registry "pending"),
W4「散戶接盤」整期無法觸發(AUDIT-golden-list-20260922 §8 #4)。市場總融資
(marketMeta.marginBalance)不是個股值,不能替代。
落地掛在 feature_flags.engine_correction_v1 之後 —— 它會改變資料完整度分級
(_COMPLETENESS_FIELDS 含 margin_balance),屬判斷改變,與其他修正同日切換。
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
_TOOLS = _AI_STOCK / "tools"
for p in (_AI_STOCK, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fetch_twse import _parse_margin_by_stock  # noqa: E402
from core.ingest import _abstain_stock_record  # noqa: E402

_FIELDS = ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額",
           "買進", "賣出", "現券償還", "前日餘額", "今日餘額", "次一營業日限額", "資券互抵", "註記"]


def _payload(*rows):
    return {"stat": "OK", "date": "20260922", "tables": [
        {"title": "信用交易統計", "fields": ["項目", "買進", "賣出", "現金(券)償還", "前日餘額", "今日餘額"],
         "data": [["融資(交易單位)", "418,648", "494,171", "9,573", "9,330,467", "9,245,371"]]},
        {"title": "融資融券彙總 (全部)", "fields": _FIELDS, "data": list(rows)}]}


def _row(code, prev, today):
    return [code, "名", "0", "0", "0", prev, today, "0", "0", "0", "0", "0", "0", "0", "0", " "]


def test_parses_per_stock_margin_balance_and_change():
    out = _parse_margin_by_stock(_payload(
        _row("1101", "37,776", "36,390"),      # 減少
        _row("2330", "10,000", "12,500"),      # 增加
        _row("0050", "1,000", "2,000"),        # ETF 跳過
    ))
    assert out == {"1101": {"balance": 36390, "change": -1386},
                   "2330": {"balance": 12500, "change": 2500}}


def test_market_total_table_is_not_mistaken_for_stocks():
    assert _parse_margin_by_stock({"tables": [_payload()["tables"][0]]}) == {}
    assert _parse_margin_by_stock({}) == {}


def test_landing_is_flag_gated():
    raw = {"name": "台積電", "margin_balance": 12500, "margin_change": 2500}
    assert _abstain_stock_record("2330", raw, has_branches=False)["margin_balance"] is None
    on = _abstain_stock_record("2330", raw, has_branches=False, correction=True)
    assert on["margin_balance"] == 12500 and on["margin_change"] == 2500


def test_w4_counters_need_the_flag_and_count_price_down_margin_up():
    from core.market_context import temporal_enrich
    def snap(date, chg, mchg):
        return {"date": date, "stocks": [{"ticker": "2330", "main_force_buy": 10,
                                          "change_pct": chg, "margin_change": mchg}]}
    prior = [snap("2026-09-01", -1.0, 500), snap("2026-09-02", -0.5, 300), snap("2026-09-03", 1.0, 400)]
    today = {"ticker": "2330", "main_force_buy": 10, "change_pct": -2.0, "margin_change": 700}
    assert temporal_enrich("2330", prior, today)["price_down_margin_up_days_10d"] is None
    te = temporal_enrich("2330", prior, today, correction=True)
    assert te["price_down_margin_up_days_10d"] == 3        # 9/01、9/02、今天
    assert te["price_down_margin_down_days_10d"] == 0
