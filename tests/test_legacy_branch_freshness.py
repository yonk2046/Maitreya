"""Per-ticker branch freshness gate — 修正案 C-2 (過期跨日殘資料).

Covers `data.adapters.legacy`:
  - a branch file whose fetched_date < snapshot date is abstained (derived
    branch fields absent, _branches_present=False), same path as "no file";
  - a same-day (or newer) branch file is used as before;
  - with no fetched_date field, freshness falls back to the file's mtime date;
  - the gate is per-ticker — a stale file never poisons a fresh sibling.

These exercise the adapter through `paths_override`, exactly how
tools/verify_all_replay.py drives it, so the fixtures double as a guard that
the freshness logic is reachable via the real code path.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from data.adapters.legacy import adapt_legacy  # noqa: E402


TARGET_DATE = "2026-07-21"


def _branch_payload(ticker: str, fetched_date: str | None) -> dict:
    d = {
        "ticker": ticker,
        "buyBranches": [
            {"broker": "凱基-台北", "buyVol": 500, "sellVol": 0, "netBuy": 500, "pct": 12.3},
        ],
        "sellBranches": [],
        "totalBuyVol": 500,
        "totalSellVol": 0,
        "avgBuyCost": 42.0,
        "avgSellCost": 41.0,
    }
    if fetched_date is not None:
        d["fetched_date"] = fetched_date
    return d


def _set_mtime_date(path: pathlib.Path, date_iso: str) -> None:
    """Force a file's mtime to noon UTC of `date_iso` (so its UTC date is stable)."""
    d = dt.date.fromisoformat(date_iso)
    ts = dt.datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=dt.timezone.utc).timestamp()
    os.utime(path, (ts, ts))


def _make_env(tmp_path: pathlib.Path, tickers: list[str]) -> dict[str, pathlib.Path]:
    root = tmp_path
    (root / "data").mkdir(parents=True, exist_ok=True)
    branches_dir = root / "data" / "branches"
    branches_dir.mkdir(parents=True, exist_ok=True)
    today = {
        "tradingDate": TARGET_DATE,
        "mainForceBuy": [
            {"code": t, "name": f"股{t}", "rank": i + 1, "close": 50.0, "chgPct": 1.0,
             "buyVol": 300}
            for i, t in enumerate(tickers)
        ],
    }
    today_path = root / "data" / "today.json"
    today_path.write_text(json.dumps(today, ensure_ascii=False), encoding="utf-8")
    return {
        "root": root,
        "today_json": today_path,
        "branches_dir": branches_dir,
        "snapshots": root / "data" / "snapshots",
    }


def _run(paths: dict[str, pathlib.Path], *, mtime_fallback: bool = True) -> dict:
    # Tests drive the adapter via paths_override (like verify_all_replay), which
    # defaults mtime_fallback off (replay). Most tests want live semantics, so
    # force it on here; replay-specific tests pass mtime_fallback=False.
    return adapt_legacy(
        date=TARGET_DATE, paths_override=paths, branch_mtime_fallback=mtime_fallback
    )


# ── fetched_date-based freshness ────────────────────────────────────────────────

def test_stale_fetched_date_abstains(tmp_path):
    paths = _make_env(tmp_path, ["2208"])
    # branch stuck on 7/13 while snapshot is 7/21 → stale
    (paths["branches_dir"] / "2208.json").write_text(
        json.dumps(_branch_payload("2208", "2026-07-13"), ensure_ascii=False),
        encoding="utf-8",
    )
    out = _run(paths)
    ri = out["raw_inputs_per_ticker"]["2208"]
    assert ri["_branches_present"] is False
    assert ri["top5_branches"] == []
    assert "total_buy_vol" not in ri and "avg_buy_cost" not in ri
    warned = [e for e in out["audit_events"]
              if e.get("ticker") == "2208" and "stale cross-day" in e["reason"]]
    assert len(warned) == 1


def test_same_day_fetched_date_is_fresh(tmp_path):
    paths = _make_env(tmp_path, ["2208"])
    (paths["branches_dir"] / "2208.json").write_text(
        json.dumps(_branch_payload("2208", TARGET_DATE), ensure_ascii=False),
        encoding="utf-8",
    )
    out = _run(paths)
    ri = out["raw_inputs_per_ticker"]["2208"]
    assert ri["_branches_present"] is True
    assert ri["total_buy_vol"] == 500
    assert ri["avg_buy_cost"] == 42.0
    assert len(ri["top5_branches"]) == 1


def test_newer_fetched_date_is_fresh(tmp_path):
    # A file dated AFTER target (e.g. replaying an older snapshot against a
    # later archive) counts as fresh — never abstained.
    paths = _make_env(tmp_path, ["2208"])
    (paths["branches_dir"] / "2208.json").write_text(
        json.dumps(_branch_payload("2208", "2026-07-25"), ensure_ascii=False),
        encoding="utf-8",
    )
    out = _run(paths)
    assert out["raw_inputs_per_ticker"]["2208"]["_branches_present"] is True


# ── mtime fallback (no fetched_date) ────────────────────────────────────────────

def test_no_fetched_date_falls_back_to_stale_mtime(tmp_path):
    paths = _make_env(tmp_path, ["2208"])
    f = paths["branches_dir"] / "2208.json"
    f.write_text(json.dumps(_branch_payload("2208", None), ensure_ascii=False),
                 encoding="utf-8")
    _set_mtime_date(f, "2026-07-13")  # old mtime, no fetched_date field
    out = _run(paths)
    assert out["raw_inputs_per_ticker"]["2208"]["_branches_present"] is False


def test_no_fetched_date_fresh_mtime_is_used(tmp_path):
    paths = _make_env(tmp_path, ["2208"])
    f = paths["branches_dir"] / "2208.json"
    f.write_text(json.dumps(_branch_payload("2208", None), ensure_ascii=False),
                 encoding="utf-8")
    _set_mtime_date(f, TARGET_DATE)
    out = _run(paths)
    assert out["raw_inputs_per_ticker"]["2208"]["_branches_present"] is True


def test_evening_mtime_not_misjudged_stale(tmp_path):
    # Regression: a file fetched on the trading-day evening (Taiwan) must not be
    # rolled back to the previous calendar day. mtime freshness uses LOCAL date
    # (matching fetch_sinotrade's date.today()), so a same-day evening mtime is
    # fresh even though its UTC date would be the prior day.
    paths = _make_env(tmp_path, ["2208"])
    f = paths["branches_dir"] / "2208.json"
    f.write_text(json.dumps(_branch_payload("2208", None), ensure_ascii=False),
                 encoding="utf-8")
    # 21:00 local on target date — UTC (‑8h) would be same day here, but the
    # point is the gate reads the LOCAL calendar date, which is target date.
    d = dt.date.fromisoformat(TARGET_DATE)
    ts = dt.datetime(d.year, d.month, d.day, 21, 30, 0).timestamp()  # naive local
    os.utime(f, (ts, ts))
    out = _run(paths)
    assert out["raw_inputs_per_ticker"]["2208"]["_branches_present"] is True


def test_replay_mode_ignores_stale_mtime_without_fetched_date(tmp_path):
    # As-was guarantee (C10): in replay (mtime_fallback off), a legacy archived
    # branch file with no fetched_date and an old mtime must NOT be flagged
    # stale — replay reproduces the snapshot as it was built before this gate.
    paths = _make_env(tmp_path, ["2208"])
    f = paths["branches_dir"] / "2208.json"
    f.write_text(json.dumps(_branch_payload("2208", None), ensure_ascii=False),
                 encoding="utf-8")
    _set_mtime_date(f, "2026-07-02")  # old, no fetched_date
    out = _run(paths, mtime_fallback=False)  # replay semantics
    assert out["raw_inputs_per_ticker"]["2208"]["_branches_present"] is True


def test_replay_mode_still_gates_on_fetched_date(tmp_path):
    # In replay, a FUTURE snapshot's archived file DOES carry fetched_date, so
    # its staleness decision must still reproduce (authoritative, both modes).
    paths = _make_env(tmp_path, ["2208"])
    (paths["branches_dir"] / "2208.json").write_text(
        json.dumps(_branch_payload("2208", "2026-07-13"), ensure_ascii=False),
        encoding="utf-8",
    )
    out = _run(paths, mtime_fallback=False)  # replay semantics
    assert out["raw_inputs_per_ticker"]["2208"]["_branches_present"] is False


# ── live corpus invariant (修正案 C-3) ──────────────────────────────────────────

def test_every_live_branch_file_carries_fetched_date():
    """每個活的 data/branches/*.json 都必須帶 fetched_date。

    這是 C-2 守門能同時滿足兩個要求的前提:

      - 舊快照(守門上線前建的)replay 不得回頭棄權 → 所以 replay 不看 mtime;
      - 新快照的 live 與 replay 判定必須一致 → 所以新快照吃到的檔案不能只有 mtime。

    只要活檔案裡有一個沒蓋章,兩者就會分歧:live 讀 mtime 判 stale 而棄權、
    replay 讀不到 mtime 於是照用 → canonical hash 不同 → verify_all_replay 紅。
    2026-07-24 快照就是這樣爆的(140/190 檔未蓋章),已由
    tools/migrate_branch_fetched_date.py 補齊。新檔由 fetch_sinotrade.py 蓋章。
    """
    branches = _AI_STOCK / "data" / "branches"
    if not branches.is_dir():
        pytest.skip("no live branches dir")
    missing = [
        f.name for f in sorted(branches.glob("*.json"))
        if not (json.loads(f.read_text(encoding="utf-8")) or {}).get("fetched_date")
    ]
    assert not missing, (
        f"{len(missing)} 個分點檔沒有 fetched_date(live/replay 會分歧):"
        f"{missing[:10]}… 跑 `python3 tools/migrate_branch_fetched_date.py` 補蓋")


# ── per-ticker isolation ────────────────────────────────────────────────────────

def test_stale_ticker_does_not_affect_fresh_sibling(tmp_path):
    paths = _make_env(tmp_path, ["2208", "3481"])
    (paths["branches_dir"] / "2208.json").write_text(
        json.dumps(_branch_payload("2208", "2026-07-02"), ensure_ascii=False),
        encoding="utf-8",
    )
    (paths["branches_dir"] / "3481.json").write_text(
        json.dumps(_branch_payload("3481", TARGET_DATE), ensure_ascii=False),
        encoding="utf-8",
    )
    out = _run(paths)
    assert out["raw_inputs_per_ticker"]["2208"]["_branches_present"] is False
    fresh = out["raw_inputs_per_ticker"]["3481"]
    assert fresh["_branches_present"] is True
    assert fresh["total_buy_vol"] == 500
