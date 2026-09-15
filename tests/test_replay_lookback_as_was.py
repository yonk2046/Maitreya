"""守門員:後補插入的快照不得滲進「建置時不存在它」的快照之 replay 歷史(C10 as-was)。

2026-09-15 背景:9/14 原始資料在隔日救回,要補建正式快照時,9/15 已經存在且是在
「沒有 9/14」的情況下建成的。舊的 replay 從**當前 index** 重算前序快照,插入 9/14 後
9/15 的 replay 會多一天歷史 → 連買天數、速度等 O 欄位全變 → 驗證失敗,只能把 9/15
也 supersede 重建。

每份快照本來就在 `environment.lookback_snapshots` 記錄了建置時實際用到的前序日期。
replay 改為只取這個日期集合,9/15 就能照「當時的樣子」重現,補插 9/14 不再牽動它。
"""
from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.verify_all_replay import _gather_lookback  # noqa: E402


def _index(*dates):
    return {"snapshots": {d: {"current_hash": f"sha256:{d}"} for d in dates}}


def test_later_inserted_prior_does_not_leak_into_recorded_history():
    # 9/15 建置時只有 9/03、9/04;9/14 是事後補插的
    idx = _index("2026-09-03", "2026-09-04", "2026-09-14", "2026-09-15")
    recorded = {"2026-09-03": "sha256:2026-09-03", "2026-09-04": "sha256:2026-09-04"}
    got = _gather_lookback("2026-09-15", 20, idx, recorded=recorded)
    assert "2026-09-14" not in got, "事後補插的 9/14 滲進了 9/15 的 replay 歷史"
    assert set(got) == {"2026-09-03", "2026-09-04"}


def test_without_record_behaves_as_before():
    """舊 epoch 沒有記錄前序 → 照舊依 window 重算(含補插日)。"""
    idx = _index("2026-09-03", "2026-09-14", "2026-09-15")
    got = _gather_lookback("2026-09-15", 20, idx, recorded=None)
    assert set(got) == {"2026-09-03", "2026-09-14"}


def test_empty_record_means_built_without_priors():
    idx = _index("2026-09-03", "2026-09-15")
    assert _gather_lookback("2026-09-15", 20, idx, recorded={}) == {}


def test_hashes_still_come_from_index():
    """只取紀錄的**日期**;hash 仍用 index 當前值(維持既有行為,例如 7/13 的前序曾於 7/14 重建)。"""
    idx = _index("2026-09-03", "2026-09-15")
    got = _gather_lookback("2026-09-15", 20, idx, recorded={"2026-09-03": "sha256:OLD-VERSION"})
    assert got == {"2026-09-03": "sha256:2026-09-03"}
