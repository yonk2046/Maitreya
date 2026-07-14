"""Tests for fetch_daily Step 9 多源交叉驗證 (R8 查證後的修正).

R8 (docs/FORWARD-RISK-REGISTER.md) 原始觀察：多源驗證「天天輸出 0/10 重疊」。
實測 27 天封存 today.json 後查證結論：
  1. 不是恆定失敗——大多數交易日重疊數會隨真實資料波動(常見 5-10/10)。
  2. 但長期系統性偏低：T86 全市場榜單原始未濾 ETF，Fubon 榜單已濾 ETF，
     兩側口徑不一致會把重疊數壓低(0050/00631L 這類 ETF 常年高居 T86 三大
     法人買賣超金額榜前段，擠掉個股排名)。
  3. T86 當天完全無資料時(抓取失敗或非交易日，如 7/10 颱風假)，舊版會輸出
     假 0/10、0/5，與「比對過但真的沒有重疊」無法區分——這兩者是不同訊息。

這裡測試修正後的 compute_cross_verify_overlap()：ETF 口徑統一 + tri-state。
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools.fetch_daily import compute_cross_verify_overlap  # noqa: E402


def _fubon(codes):
    return [{"code": c} for c in codes]


def test_t86_empty_is_disabled_not_fake_zero():
    """T86 完全無資料(抓取失敗/非交易日)——status 必須是 disabled，附原因，
    不可靜默回傳看起來像「比對過、無重疊」的 0/0。"""
    cv = compute_cross_verify_overlap(_fubon(["2330"]), _fubon(["2330"]), {})
    assert cv["status"] == "disabled"
    assert "disabledReason" in cv and cv["disabledReason"]
    assert cv["foreignOverlap"] == 0
    assert cv["mainforceOverlap"] == 0


def test_ok_status_when_t86_has_data():
    t86 = {"2330": {"code": "2330", "foreign": 100, "total3": 100}}
    cv = compute_cross_verify_overlap(_fubon(["2330"]), _fubon(["2330"]), t86)
    assert cv["status"] == "ok"


def test_etf_excluded_from_t86_side_before_ranking():
    """T86 榜單比對前必須濾掉 ETF(比照 Fubon 抓取時已濾除的口徑)——否則
    ETF(00 開頭代碼)長年霸榜會把個股排擠出 top-N，系統性壓低重疊數。"""
    # T86 全市場：0050(ETF, foreign 巨量)排第一, 2330 其次, 2317 第三
    t86 = {
        "0050":  {"code": "0050",  "foreign": 99999, "total3": 99999},
        "2330":  {"code": "2330",  "foreign": 500,    "total3": 500},
        "2317":  {"code": "2317",  "foreign": 400,    "total3": 400},
    }
    fubon_top = _fubon(["2330", "2317"])  # Fubon 已濾 ETF,只剩個股
    cv = compute_cross_verify_overlap(fubon_top, fubon_top, t86)
    # 若未濾 ETF：t86 top-N 會被 0050 佔位，重疊數被低估。
    # 濾除後：兩側都是純個股榜單，2330/2317 應完整重疊。
    assert cv["foreignOverlap"] == 2
    assert cv["mainforceOverlap"] == 2
    assert "0050" not in cv["t86ForeignTop10"]
    assert "0050" not in cv["t86Total3Top5"]


def test_overlap_counts_real_stocks_correctly():
    t86 = {
        "2330": {"code": "2330", "foreign": 1000, "total3": 900},
        "2317": {"code": "2317", "foreign": 800,  "total3": 700},
        "9999": {"code": "9999", "foreign": 1,    "total3": 1},
    }
    fubon_foreign = _fubon(["2330", "2317"])
    fubon_main = _fubon(["2330"])
    cv = compute_cross_verify_overlap(fubon_foreign, fubon_main, t86)
    assert cv["foreignOverlap"] == 2
    assert cv["mainforceOverlap"] == 1


def test_empty_fubon_lists_leave_overlap_zero_without_crashing():
    t86 = {"2330": {"code": "2330", "foreign": 1, "total3": 1}}
    cv = compute_cross_verify_overlap([], [], t86)
    assert cv["status"] == "ok"
    assert cv["foreignOverlap"] == 0
    assert cv["mainforceOverlap"] == 0
