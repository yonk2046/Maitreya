"""Test the TWSE STOCK_DAY_ALL open-price parser (P3b backtest settlement).

The live fetch needs network, so we test the pure parse helper against sample
rows in both the English and Chinese key shapes TWSE OpenAPI returns.
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

from fetch_twse import _parse_open_map  # noqa: E402


def test_parse_english_keys():
    data = [
        {"Code": "2330", "Name": "台積電", "OpeningPrice": "1085.00", "ClosingPrice": "1090.00"},
        {"Code": "2344", "Name": "華邦電", "OpeningPrice": "31.50"},
    ]
    out = _parse_open_map(data)
    assert out == {"2330": 1085.0, "2344": 31.5}


def test_parse_chinese_keys():
    data = [{"證券代號": "2408", "開盤價": "505.0"}]
    assert _parse_open_map(data) == {"2408": 505.0}


def test_skips_etfs_and_blank_open():
    data = [
        {"Code": "0050", "OpeningPrice": "190.0"},   # ETF skipped
        {"Code": "2890", "OpeningPrice": "0"},        # no real open → skipped
        {"Code": "6239", "OpeningPrice": "104.0"},
    ]
    assert _parse_open_map(data) == {"6239": 104.0}


def test_empty_and_none_safe():
    assert _parse_open_map([]) == {}
    assert _parse_open_map(None) == {}
