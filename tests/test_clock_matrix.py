"""時鐘矩陣 —— 凍結「時刻 × 日型」去斷言會讀時鐘的判斷點。

## 為什麼需要這一檔(2026-07-28 起草,見 docs/FAILURE-MODE-INDEX.md)

`make test` 與 `verify_all_replay` 都固定在「執行的那一刻 × 凍結語料」,結構上
不可能變動 pipeline 真正活著的四軸:時刻 T / 日型 D / 執行者 M / 上游 U。
已發生的七件事故有五件住在那個測不到的象限裡 —— 這就是「改一改、隔天壞掉」
的固定形狀。

## 這一檔補的是「接縫」,不是判斷點本身

盤點後發現多數判斷點**各自已有測試**:
  - `_intraday_guard_disposition` → tests/test_daily.py 純矩陣(含 8:59/9:00 邊界)
  - `_trading_day_oracle`         → tests/test_partial_snapshot.py(含 7/10 颱風假)
  - `remote-first gate`           → tests/test_daily.py 純矩陣
  - `_branch_stale`               → tests/test_legacy_branch_freshness.py

而 7/25 與 7/28 兩次事故,壞的都**不是判斷點,是接縫**:元件各自正確,但沒接上
(fetch_sinotrade 從來沒收到交易日)、或順序錯了(抓取跑在守門員前面)。
所以本檔只做兩件現有測試沒做的事:

  A. `derive_trading_date` 的凍結時鐘矩陣 —— 它**零測試**,卻在 2026-07-28 的
     C-2 修法後變成 branch 戳記的唯一來源(載重元件無測試 = 新開的洞)。
  B. **產物不變式** —— 直接斷言磁碟上的結果,不管是哪個 runner、幾點鐘寫的。
     接縫 bug 從輸出端看得見,從單元測試看不見。
"""
from __future__ import annotations

import datetime
import glob
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools import fetch_daily  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# A. derive_trading_date —— 凍結時鐘矩陣
# ══════════════════════════════════════════════════════════════════════════

class _ClockStub:
    """替換 fetch_daily 模組內的 `datetime`,讓 datetime.now() 回傳凍結時刻。

    derive_trading_date 內部另外 `from datetime import timedelta`(函式內 import),
    不受影響 —— 只有 now() 被凍結。
    """

    def __init__(self, moment: datetime.datetime):
        self._moment = moment

    def now(self):
        return self._moment


def _resolve(monkeypatch, moment: datetime.datetime, twse_yyyymmdd: str | None):
    monkeypatch.setattr(fetch_daily, "datetime", _ClockStub(moment))
    twse = {"tradingDate": twse_yyyymmdd} if twse_yyyymmdd else None
    return fetch_daily.derive_trading_date(twse)


def test_premarket_never_claims_today(monkeypatch):
    """**C-2 修法的地基**:盤前跑,解出的交易日絕不可以是今天。

    2026-07-28(二)08:35 的 T+1 補跑抓到的是 7/27 盤後的分點。若這裡回今天,
    branch 戳記就會蓋成 7/28,C-2 鮮度閘門(`fd < target`)便會放行昨日殘值。
    """
    got = _resolve(monkeypatch, datetime.datetime(2026, 7, 28, 8, 35), "20260727")
    assert got == "2026-07-27", "盤前必須回前一 session,不得回今天"


def test_intraday_never_claims_today(monkeypatch):
    """cron 漂移進盤中(11:55)同理 —— 收盤前不存在「今天的盤後資料」。"""
    got = _resolve(monkeypatch, datetime.datetime(2026, 7, 28, 11, 55), "20260727")
    assert got == "2026-07-27"


def test_after_close_advances_past_lagging_twse(monkeypatch):
    """盤後 19:00:TWSE T86 慣性落後一天,此時才可以用今天覆蓋它。"""
    got = _resolve(monkeypatch, datetime.datetime(2026, 7, 28, 19, 0), "20260727")
    assert got == "2026-07-28"


def test_weekend_never_returns_a_weekend(monkeypatch):
    """週六 11:52 跑(7/25 事故的時刻)——分點是交易日盤後產物,
    解出的交易日不可以是週末。"""
    got = _resolve(monkeypatch, datetime.datetime(2026, 7, 25, 11, 52), "20260724")
    assert got == "2026-07-24"

    # TWSE 也掛掉時走 last-weekday fallback,同樣不得回週末
    got_no_twse = _resolve(monkeypatch, datetime.datetime(2026, 7, 26, 11, 52), None)
    assert datetime.date.fromisoformat(got_no_twse).weekday() < 5, \
        f"fallback 回了週末日期 {got_no_twse}"


# ══════════════════════════════════════════════════════════════════════════
# B. 產物不變式 —— 不管誰、幾點寫的,磁碟上的結果必須成立
# ══════════════════════════════════════════════════════════════════════════

# 前向生效(對齊憲法 C10/C11 forward-only):C-2 修法 2026-07-28 落地,
# 在此之前的殘留戳記為既成歷史(下次抓取該檔時自然被覆蓋),不回頭改。
# 落地當下實測有 16 檔週末戳記殘留:7/25(6)、7/26(8)、6/27(2)。
_FIX_EPOCH = "2026-07-28"


def _branch_stamps():
    for path in sorted(glob.glob(str(_AI_STOCK / "data" / "branches" / "*.json"))):
        try:
            data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fd = data.get("fetched_date")
        if isinstance(fd, str) and len(fd) == 10:
            yield pathlib.Path(path).name, fd


def test_no_new_weekend_branch_stamps():
    """分點是**交易日盤後**產物 —— 週末戳記在定義上不可能存在。

    這條從輸出端抓接縫 bug:不管是早班 GHA、傍晚 launchd 還是手動補跑寫的,
    只要有人再把日曆日當資料日蓋上去,這裡就紅。
    """
    offenders = [
        (name, fd) for name, fd in _branch_stamps()
        if fd >= _FIX_EPOCH and datetime.date.fromisoformat(fd).weekday() >= 5
    ]
    assert not offenders, (
        f"{len(offenders)} 個 branch 檔帶週末 fetched_date(分點不可能是週末產物):"
        f"{offenders[:5]}"
    )


def test_no_branch_stamp_from_the_future():
    """戳記不得晚於今天 —— 未來日期代表時鐘/時區/日期來源出錯。"""
    today = datetime.date.today().isoformat()
    future = [(name, fd) for name, fd in _branch_stamps() if fd > today]
    assert not future, f"branch 戳記出現未來日期(今天 {today}):{future[:5]}"
