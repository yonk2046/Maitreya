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


# ── A4 (2026-09-22): session-dated MI_INDEX quotes ──────────────────────────
from fetch_twse import _parse_mi_index_quotes  # noqa: E402

_MI_FIELDS = ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價",
              "收盤價", "漲跌(+/-)", "漲跌價差", "最後揭示買價", "最後揭示買量", "最後揭示賣價",
              "最後揭示賣量", "本益比"]


def _mi(*rows):
    return {"stat": "OK", "date": "20260903",
            "tables": [{"title": "大盤統計", "fields": ["指數", "收盤指數"], "data": [["x", "1"]]},
                       {"title": "每日收盤行情", "fields": _MI_FIELDS, "data": list(rows)}]}


def _row(code, vol, op, close, sign, chg):
    return [code, "名", vol, "1", "1", op, op, op, close, sign, chg, "0", "0", "0", "0", "0"]


def test_mi_index_parses_session_open_and_signed_change():
    op, q = _parse_mi_index_quotes(_mi(
        _row("2303", "44,470,000", "127.50", "126.00", "<p style= color:green>-</p>", "5.50"),
        _row("2330", "31,855,287", "2,395.00", "2,440.00", "<p style= color:red>+</p>", "35.00"),
        _row("0050", "1,000", "190.0", "191.0", "<p style= color:red>+</p>", "1.00"),       # ETF
        _row("9999", "0", "--", "--", " ", "0.00"),                                         # 停牌
    ))
    assert op == {"2303": 127.5, "2330": 2395.0}          # 9/3 真開盤 127.50(非 9/2 的 131.5)
    assert q["2303"]["vol"] == 44470 and q["2303"]["chgAmt"] == -5.5
    assert q["2303"]["chgPct"] == round(-5.5 / 131.5 * 100, 2)
    assert q["2330"]["chgPct"] == round(35 / 2405 * 100, 2)
    assert set(q) == {"2303", "2330"}


def test_mi_index_empty_safe():
    assert _parse_mi_index_quotes({}) == ({}, {})
    assert _parse_mi_index_quotes(None) == ({}, {})


# ── A4 adapter precedence on a real archived raw (2026-09-22) ─────────────
import json as _json  # noqa: E402
import shutil as _shutil  # noqa: E402

from data.adapters.legacy import adapt_legacy  # noqa: E402

_ARCH = _AI_STOCK / "reports" / "_raw_archive" / "2026-09-22"


def _adapt_with(tmp_path, qbd):
    today = _json.loads((_ARCH / "legacy_today_json" / "today.json").read_text(encoding="utf-8"))
    if qbd is not None:
        today["quotesByDate"] = qbd
    tj = tmp_path / "today.json"
    tj.write_text(_json.dumps(today, ensure_ascii=False), encoding="utf-8")
    out = adapt_legacy(date="2026-09-22", paths_override={
        "root": _AI_STOCK, "today_json": tj, "branches_dir": _ARCH / "legacy_branches",
        "snapshots": _AI_STOCK / "data" / "snapshots"}, tdcc_asof="1900-01-01")
    return out["raw_inputs_per_ticker"]


def test_adapter_prefers_session_dated_quotes_only_for_same_date(tmp_path):
    base = _adapt_with(tmp_path, None)                       # 封存原樣(A4 前)
    t = next(iter(base))
    fake = {"openPrices": {t: 1.23}, "marketQuotes": {t: {"vol": 7, "close": 9.0, "chgPct": 4.56, "chgAmt": 0.4}}}
    same = _adapt_with(tmp_path, {"date": "20260922", **fake})
    assert same[t]["open"] == 1.23 and same[t]["market_volume"] == 7 and same[t]["change_pct"] == 4.56
    other = _adapt_with(tmp_path, {"date": "20260919", **fake})   # 別天的 → 不採用
    assert other[t]["open"] == base[t]["open"]
    assert other[t]["market_volume"] == base[t]["market_volume"]
    assert other[t]["change_pct"] == base[t]["change_pct"]
