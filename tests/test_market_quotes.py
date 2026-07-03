"""A2 fix (2026-07-03): full-market volume + real-percent change.

Covers:
  - fetch_twse._parse_market_quotes  (STOCK_DAY_ALL → {code: vol張/close/chgPct/chgAmt})
  - fetch_fubon._real_chg_pct        (Fubon 「漲跌」欄是元, 轉真%)

Live fetches need network, so only the pure helpers are tested.
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

from fetch_twse import _parse_market_quotes  # noqa: E402
from fetch_fubon import _real_chg_pct        # noqa: E402


# ── _parse_market_quotes ────────────────────────────────────────────────────

def test_quotes_volume_converted_to_lots():
    # 聯電 2026-07-02 real case: 244,699,836 股 → 244,700 張
    data = [{"Code": "2303", "Name": "聯電", "TradeVolume": "244,699,836",
             "ClosingPrice": "169.00", "Change": "4.5000"}]
    out = _parse_market_quotes(data)
    assert out["2303"]["vol"] == 244700
    assert out["2303"]["close"] == 169.0


def test_quotes_change_is_real_percent_not_ntd():
    # +4.5 元 on close 169 → prev 164.5 → +2.74%, NOT 4.5%
    data = [{"Code": "2303", "TradeVolume": "1000", "ClosingPrice": "169.0", "Change": "4.5"}]
    q = _parse_market_quotes(data)["2303"]
    assert q["chgPct"] == 2.74
    assert q["chgAmt"] == 4.5


def test_quotes_high_priced_stock_regression():
    # 國巨-style: +100 元 on 1140 → +9.62%, the 730fd4d regression case
    data = [{"Code": "2327", "TradeVolume": "5,000,000", "ClosingPrice": "1140", "Change": "100"}]
    q = _parse_market_quotes(data)["2327"]
    assert q["chgPct"] == 9.62
    assert q["vol"] == 5000
    assert q["chgPct"] != 100.0


def test_quotes_negative_change():
    data = [{"Code": "1303", "TradeVolume": "10,247,000", "ClosingPrice": "40.0", "Change": "-1.0"}]
    q = _parse_market_quotes(data)["1303"]
    assert q["chgPct"] == -2.44
    assert q["chgAmt"] == -1.0


def test_quotes_skips_etf_and_no_close():
    data = [
        {"Code": "0050", "TradeVolume": "999", "ClosingPrice": "190", "Change": "1"},  # ETF
        {"Code": "9999", "TradeVolume": "999", "ClosingPrice": "0", "Change": "0"},    # no close
        {"Code": "2330", "TradeVolume": "30,000,000", "ClosingPrice": "1090", "Change": "10"},
    ]
    out = _parse_market_quotes(data)
    assert set(out.keys()) == {"2330"}


def test_quotes_chinese_keys_and_empty_safe():
    data = [{"證券代號": "2408", "成交股數": "8,000,000", "收盤價": "505", "漲跌價差": "5"}]
    out = _parse_market_quotes(data)
    assert out["2408"]["vol"] == 8000
    assert _parse_market_quotes([]) == {}
    assert _parse_market_quotes(None) == {}


# ── fetch_fubon._real_chg_pct ───────────────────────────────────────────────

def test_fubon_real_pct():
    assert _real_chg_pct(169.0, 4.5) == 2.74          # 聯電 case
    assert _real_chg_pct(1140.0, 100.0) == 9.62       # 國巨 case (曾誤標 100%)
    assert _real_chg_pct(40.0, -1.0) == -2.44         # 下跌
    assert _real_chg_pct(0, 0) == 0.0                 # degenerate → 0, no crash
    assert _real_chg_pct(None, None) == 0.0


# ── adapter merge: marketQuotes 優先, 舊 raw 無此區塊走原路 ────────────────

def test_adapter_market_quotes_merge_logic():
    """Replicates the legacy.py merge branch: mq overrides top20 fallback;
    absence of marketQuotes (old raw archives) keeps prior behaviour."""
    vol_map = {"2303": 99}          # stale top20-derived value
    market_quotes = {"2303": {"vol": 244700, "close": 169.0, "chgPct": 2.74, "chgAmt": 4.5}}

    def merge(ticker, ri, quotes):
        mq = quotes.get(ticker)
        if mq and mq.get("vol"):
            ri["market_volume"] = mq["vol"]
        else:
            ri["market_volume"] = vol_map.get(ticker)
        if mq and mq.get("chgPct") is not None:
            ri["change_pct"] = mq["chgPct"]
        return ri

    # with marketQuotes → full-market value + authoritative %
    ri = merge("2303", {"change_pct": 4.5}, market_quotes)
    assert ri["market_volume"] == 244700
    assert ri["change_pct"] == 2.74

    # old raw (no marketQuotes) → prior behaviour, untouched change_pct
    ri = merge("2303", {"change_pct": 4.5}, {})
    assert ri["market_volume"] == 99
    assert ri["change_pct"] == 4.5

    # not in any source → None
    ri = merge("1710", {"change_pct": 1.0}, {})
    assert ri["market_volume"] is None
    assert ri["change_pct"] == 1.0
