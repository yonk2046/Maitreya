"""分點 branch 檔的 fetched_date 必須記「資料所屬交易日」,不是執行當天的日曆日。

2026-07-28 查出:GHA 早班 T+1 補跑(daily.yml `35 0 * * 2-6`,08:35 盤前)抓到的
是**前一個 session** 的分點,但 fetch_sinotrade 一律用 `date.today()` 蓋戳,於是
昨日資料被標成今天。legacy.py 的 C-2 鮮度閘門判斷式是 `fetched_date < target_date`
→ 戳成今天就「不小於」→ 判定新鮮而放行,正好是 C-2 當初要擋的那件事。

平常被傍晚那趟重抓覆蓋所以看不出來;傍晚對某檔抓取失敗時,早班殘值就會無聲頂著
今天的日期戳通過閘門。修法:由 fetch_daily 以 derive_trading_date 解出的權威交易日
傳入 session_date(與落地 "date" 欄同一來源)。
"""
from __future__ import annotations

import datetime
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
for _p in (str(_AI_STOCK), str(_AI_STOCK / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fetch_sinotrade  # noqa: E402
from data.adapters.legacy import _branch_stale  # noqa: E402


def _fetch_with_stub(monkeypatch, *args):
    """跑 fetch() 但不連網 —— 只關心 fetched_date 怎麼決定。"""
    monkeypatch.setattr(fetch_sinotrade, "http_get", lambda *a, **k: b"<html></html>")
    monkeypatch.setattr(fetch_sinotrade, "extract_table_rows", lambda *a, **k: [])
    return fetch_sinotrade.fetch(*args)


def test_session_date_wins_over_calendar_today(monkeypatch):
    """呼叫端給了交易日 → 就記交易日,不管今天是幾號。"""
    result = _fetch_with_stub(monkeypatch, "8150", "2026-07-27")
    assert result["fetched_date"] == "2026-07-27"


def test_standalone_cli_falls_back_to_today(monkeypatch):
    """獨立 CLI 執行沒有呼叫端資訊 → 維持舊行為(向後相容)。"""
    result = _fetch_with_stub(monkeypatch, "8150")
    assert result["fetched_date"] == datetime.date.today().isoformat()


def test_c2_gate_rejects_previous_session_only_when_stamped_correctly():
    """閘門後果測試 —— 說明這個戳記為什麼是對錯的分水嶺。

    早班 08:35 抓到的是 7/27 的分點。隔天傍晚要建 7/28 快照時:
      - 戳成執行日 2026-07-28(舊 bug)→ 閘門放行昨日殘值
      - 戳成所屬交易日 2026-07-27(修法後)→ 閘門正確判 stale
    """
    target = "2026-07-28"

    buggy = _branch_stale(
        {"fetched_date": "2026-07-28"}, "", target, mtime_fallback=False)
    assert buggy == (False, "2026-07-28"), "舊行為:昨日分點被誤判為新鮮"

    fixed = _branch_stale(
        {"fetched_date": "2026-07-27"}, "", target, mtime_fallback=False)
    assert fixed == (True, "2026-07-27"), "修法後:前一 session 必須判 stale"
