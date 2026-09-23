"""守門員:A7 —— 畫面的黃金名單必須等於快照落地的 obs_golden_*(AUDIT G5)。

畫面原本用 `golden.run(全歷史)`,那是第三份名單:它用整個語料判斷,並保留幾天前
就掉出主力買超榜的股票。pipeline 用該快照記錄的 lookback 窗口 + 該快照自己的
feature flag(C10 as-was),且只報當天在榜的股票。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.golden import run_as_landed  # noqa: E402


def _corpus() -> list[dict]:
    idx = json.loads((_ROOT / "reports" / "index.json").read_text())["snapshots"]
    ds = sorted(d for d, e in idx.items() if "example" not in d and "example" not in e["current"])
    return [json.loads((_ROOT / "reports" / idx[d]["current"]).read_text()) for d in ds]


def _landed(snap: dict) -> set[str]:
    return {s["ticker"] for s in snap.get("stocks", []) if s.get("obs_golden_tier")}


def _mismatch(snaps: list[dict], i: int) -> str | None:
    """None = 相符或該日未落地 O 欄(W6 backfill / 舊 epoch,本就沒有 obs_golden_* 可比)。"""
    snap = snaps[i]
    if not snap.get("obs_landing"):
        return None
    want = _landed(snap)
    got = {e.ticker for e in run_as_landed(snaps[: i + 1]).all_golden}
    if got == want:
        return None
    return f"{snap['date']}:畫面多 {sorted(got - want)}、少 {sorted(want - got)}"


def _assert_range(lo: int, hi: int) -> None:
    snaps = _corpus()
    bad = [m for m in (_mismatch(snaps, i) for i in range(lo, hi)) if m]
    assert not bad, "畫面黃金名單與快照不符:\n  " + "\n  ".join(bad)


def test_latest_five_days_match_the_snapshot():
    _assert_range(max(0, len(_corpus()) - 5), len(_corpus()))


@pytest.mark.slow
def test_whole_corpus_matches_the_snapshot():
    _assert_range(0, len(_corpus()))
