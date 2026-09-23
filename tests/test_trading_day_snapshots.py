"""守門員:index 內的快照日必須是交易日。

2026-09-23 查到 `reports/2026-05-17.json` 是**星期日**的快照(5/27 rollup 回補批次
產出,schema 1.4.0、8 檔)。WORM 不刪,但它會被當成一個交易日進入 20 日窗口與回測語料。
本測試凍結現況:除已知的那一筆外,不得再有非平日快照。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_GRANDFATHERED = {"2026-05-17"}      # 2026-05-27 rollup 回補批次的殭屍日(見 docstring)


def test_every_snapshot_date_is_a_weekday():
    idx = json.loads((_ROOT / "reports" / "index.json").read_text())["snapshots"]
    weekend = [d for d, e in idx.items()
               if "example" not in d and "example" not in e["current"]
               and dt.date.fromisoformat(d).weekday() >= 5]
    assert set(weekend) <= _GRANDFATHERED, f"新的非交易日快照: {sorted(set(weekend) - _GRANDFATHERED)}"
