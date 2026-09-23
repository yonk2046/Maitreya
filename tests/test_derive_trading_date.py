"""守門員:T2 —— derive_trading_date 的時鐘矩陣(9/15 交接 §4.4)。

兩個破洞各有事故:
  ① 過午夜:9/8 01:40 的班把 9/7 的資料建成 **9/4** 的快照(D1 混日)。
  ② 15:00–18:00:富邦 ZGK 約 18:00 才結算,此時段的主力榜還是前一天的,
     舊碼卻從 15:00 起就標成今天。
"""
from __future__ import annotations

import datetime
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fetch_daily as _fd  # noqa: E402


@pytest.fixture()
def clock(monkeypatch):
    """凍結 fetch_daily 看到的 now()。"""
    def _set(stamp: str):
        frozen = datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M")

        class _DT(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen

        monkeypatch.setattr(_fd, "datetime", _DT)
    return _set


# 2026-09-04 五 / 09-05 六 / 09-06 日 / 09-07 一 / 09-08 二
@pytest.mark.parametrize("stamp, expected", [
    ("2026-09-08 01:40", "2026-09-07"),   # ① 過午夜:D1 事故的那一班
    ("2026-09-07 16:00", "2026-09-04"),   # ② 15–18 點:ZGK 未結算,不得標今天
    ("2026-09-07 17:59", "2026-09-04"),   # ② 邊界
    ("2026-09-07 18:00", "2026-09-07"),   # ② 邊界:結算後才算今天
    ("2026-09-07 18:05", "2026-09-07"),   # 雲端主班
    ("2026-09-07 19:00", "2026-09-07"),   # Mac 備援
    ("2026-09-08 08:35", "2026-09-07"),   # T+1 早班 → 前一 session
    ("2026-09-07 13:00", "2026-09-04"),   # 盤中
    ("2026-09-05 10:00", "2026-09-04"),   # 週六
    ("2026-09-06 23:00", "2026-09-04"),   # 週日深夜 → 週五
])
def test_clock_matrix(clock, stamp, expected):
    clock(stamp)
    assert _fd.derive_trading_date(None) == expected


def test_a_lagging_twse_date_can_no_longer_win(clock):
    """TWSE OpenAPI 落後時不得再把日期拉回去 —— 那正是 D1 混日的成因。"""
    clock("2026-09-08 01:40")
    stale = {"tradingDate": "20260904"}
    assert _fd.derive_trading_date(stale) == "2026-09-07"


def test_never_stamps_a_session_that_has_not_settled(clock):
    """任何時刻解出的交易日都不得晚於『今天』,且未結算前不得等於今天。"""
    for hour in range(24):
        clock(f"2026-09-07 {hour:02d}:00")
        got = _fd.derive_trading_date(None)
        assert got <= "2026-09-07"
        if hour < 18:
            assert got < "2026-09-07"
