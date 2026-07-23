"""Tests for the branch-fetch priority list (fetch_daily Step 7).

The daily Sinotrade branch fetch is capped (~40 tickers). These tests lock the
contract that the names we actually track — 記憶體 anchors, Tier-A anchors,
prior-day golden, and high cumulative-net-buy — always survive the cap, and that
the prior-snapshot seed reads safely.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import json
import os

from tools.fetch_daily import (  # noqa: E402
    MEMORY_ANCHORS,
    build_branch_fetch_list,
    stale_backfill_candidates,
    _branch_effective_date,
    _prior_priority_from_snapshot,
    _cli_date_arg,
    _resolve_fetch_date,
)

TIER_A = ["2330", "2317", "2382", "2454", "2308", "2881", "2882", "2891"]


def _kw(**over):
    base = dict(
        memory=MEMORY_ANCHORS, tier_a=TIER_A,
        prior_golden=[], prior_high_net=[],
        cross=[], fii_top=[], mf_top=[], fii_sell_top=[], mf_sell_top=[],
        cap=40,
    )
    base.update(over)
    return base


def test_priority_order_memory_first():
    out = build_branch_fetch_list(**_kw(prior_high_net=["9999"], cross=["1111"]))
    _m = len(MEMORY_ANCHORS)
    assert out[:_m] == MEMORY_ANCHORS                    # 記憶體 anchors lead
    assert out[_m:_m + len(TIER_A)] == TIER_A            # then Tier-A
    assert "9999" in out and "1111" in out


def test_dedup_preserves_first_position():
    # a ticker appearing in both memory and today's榜 keeps its early slot once
    out = build_branch_fetch_list(**_kw(mf_top=["2344", "5555"]))
    assert out.count("2344") == 1
    assert out.index("2344") < out.index("5555")


def test_anchors_survive_the_cap():
    # flood today's rankings with 50 names; anchors must still make the 40-cap
    flood = [f"{9000 + i}" for i in range(50)]
    out = build_branch_fetch_list(**_kw(cross=flood, cap=40))
    assert len(out) == 40
    for t in MEMORY_ANCHORS + TIER_A:
        assert t in out, f"{t} dropped by cap"


def test_high_net_priority_beats_today_rankings():
    out = build_branch_fetch_list(**_kw(prior_high_net=["7777"], cross=["8888"]))
    assert out.index("7777") < out.index("8888")


def test_prior_snapshot_seed_real_data():
    golden, high_net = _prior_priority_from_snapshot(str(_AI_STOCK / "reports"))
    assert isinstance(golden, list) and isinstance(high_net, list)
    assert len(high_net) > 0          # 6/22 snapshot has net_cumulative flow
    assert all(isinstance(t, str) for t in high_net)


def test_missing_reports_dir_is_safe():
    assert _prior_priority_from_snapshot("/no/such/dir") == ([], [])


# ── market_pulse 目標日貫通 — historical backfill 抓錯天 ────────────────────
# 根因:fetch_daily.py 內呼叫 market_pulse fetch_and_write 時,fetch_date 一律
# 寫死 datetime.now(),歷史日期重建(orchestrator 路徑)因此靜默抓成「今天」的
# 大盤脈搏而非目標日。修法(比照 68d832c 對 _fetch_*_futures_html 的模式):
# run()/_resolve_fetch_date 接受可選 date_str,None 時維持 now() 行為不變。

def test_resolve_fetch_date_uses_explicit_date_not_now():
    assert _resolve_fetch_date("2026-05-25") == "2026-05-25"


def test_resolve_fetch_date_none_keeps_now_behaviour():
    from datetime import datetime as _dt
    today = _dt.now().strftime("%Y-%m-%d")
    assert _resolve_fetch_date(None) == today
    assert _resolve_fetch_date() == today


def test_cli_date_arg_parses_space_separated_form():
    assert _cli_date_arg(["fetch_daily.py", "--date", "2026-05-25"]) == "2026-05-25"


def test_cli_date_arg_parses_equals_form():
    assert _cli_date_arg(["fetch_daily.py", "--date=2026-05-25"]) == "2026-05-25"


def test_cli_date_arg_absent_returns_none():
    assert _cli_date_arg(["fetch_daily.py", "--dry-run"]) is None


def test_cli_date_arg_trailing_flag_with_no_value_returns_none():
    assert _cli_date_arg(["fetch_daily.py", "--date"]) is None


# ── 修法:賣超榜優先序對齊用途 + 最舊優先回補槽 ─────────────────────────────
# 背景:fii_sell_top/mf_sell_top 原本排在優先序最後,最容易被 cap=40 砍掉,
# 但抓賣超股是為了餵 avgSellCost/安全邊際 — 優先序與用途矛盾。修法把賣超榜
# 移到 prior_golden 之後、prior_high_net/cross 之前。另外新增「最舊優先回補
# 槽」(≤5),防止長尾股在零回補機制下永久停滯在同一天的分點快照。

def test_sell_top_now_beats_prior_high_net():
    # 賣超榜現在贏 prior_high_net —— 修法前的行為是反過來的。
    out = build_branch_fetch_list(**_kw(
        prior_high_net=["7777"], fii_sell_top=["6666"]))
    assert out.index("6666") < out.index("7777")


def test_sell_top_now_beats_cross():
    out = build_branch_fetch_list(**_kw(
        cross=["8888"], mf_sell_top=["6665"]))
    assert out.index("6665") < out.index("8888")


def test_sell_top_still_after_prior_golden():
    # 賣超榜排在 prior_golden 之後(緊接其後),不是最前面。
    out = build_branch_fetch_list(**_kw(
        prior_golden=["5555"], fii_sell_top=["6666"]))
    assert out.index("5555") < out.index("6666")


def test_stale_backfill_slot_after_anchors_before_other_rankings():
    # 回補槽排在固定 anchors(memory/tier_a)之後、其他所有榜單(含
    # prior_golden)之前。
    out = build_branch_fetch_list(**_kw(
        stale_backfill=["4444"], prior_golden=["5555"], fii_sell_top=["6666"]))
    _m = len(MEMORY_ANCHORS)
    assert out[_m + len(TIER_A)] == "4444"
    assert out.index("4444") < out.index("5555")
    assert out.index("4444") < out.index("6666")


def test_cap_still_40_with_stale_backfill():
    flood = [f"{9000 + i}" for i in range(50)]
    out = build_branch_fetch_list(**_kw(
        stale_backfill=["1", "2", "3", "4", "5"], cross=flood, cap=40))
    assert len(out) == 40
    for t in ["1", "2", "3", "4", "5"]:
        assert t in out


def _write_branch(path, fetched_date=None):
    payload = {"buyBranches": []}
    if fetched_date is not None:
        payload["fetched_date"] = fetched_date
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stale_backfill_candidates_picks_oldest_via_fetched_date(tmp_path):
    for ticker, d in [("1001", "2026-07-20"), ("1002", "2026-07-10"),
                       ("1003", "2026-07-15"), ("1004", "2026-07-01"),
                       ("1005", "2026-07-05"), ("1006", "2026-07-22")]:
        _write_branch(tmp_path / f"{ticker}.json", fetched_date=d)
    universe = ["1001", "1002", "1003", "1004", "1005", "1006"]
    out = stale_backfill_candidates(universe, str(tmp_path), n=5)
    # oldest 5 by fetched_date, ascending: 1004,1005,1002,1003,1001 (1006 dropped)
    assert out == ["1004", "1005", "1002", "1003", "1001"]


def test_stale_backfill_candidates_skips_tickers_without_local_file(tmp_path):
    _write_branch(tmp_path / "2001.json", fetched_date="2026-07-01")
    # 2002/2003 有出現在今日宇宙,但本機沒有分點檔 — 不算「該回補」的候選。
    out = stale_backfill_candidates(["2001", "2002", "2003"], str(tmp_path), n=5)
    assert out == ["2001"]


def test_stale_backfill_candidates_empty_when_no_local_files(tmp_path):
    out = stale_backfill_candidates(["3001", "3002"], str(tmp_path), n=5)
    assert out == []


def test_stale_backfill_candidates_mtime_fallback_when_no_fetched_date(tmp_path):
    import time

    old_path = tmp_path / "4001.json"
    new_path = tmp_path / "4002.json"
    _write_branch(old_path)   # no fetched_date -> mtime fallback
    _write_branch(new_path)   # no fetched_date -> mtime fallback
    old_time = time.time() - 10 * 86400
    os.utime(old_path, (old_time, old_time))
    out = stale_backfill_candidates(["4001", "4002"], str(tmp_path), n=5)
    assert out == ["4001", "4002"]


def test_stale_backfill_candidates_respects_n_limit(tmp_path):
    for i in range(8):
        _write_branch(tmp_path / f"{5000 + i}.json", fetched_date=f"2026-07-{i+1:02d}")
    universe = [str(5000 + i) for i in range(8)]
    out = stale_backfill_candidates(universe, str(tmp_path), n=5)
    assert len(out) == 5
    assert out == ["5000", "5001", "5002", "5003", "5004"]


def test_branch_effective_date_prefers_fetched_date_over_mtime(tmp_path):
    p = tmp_path / "6001.json"
    _write_branch(p, fetched_date="2026-01-01")
    # mtime is "now" (recent) but fetched_date must win.
    assert _branch_effective_date(str(p)) == "2026-01-01"


def test_branch_effective_date_none_for_missing_file(tmp_path):
    assert _branch_effective_date(str(tmp_path / "nope.json")) is None


def test_branch_effective_date_none_for_corrupt_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert _branch_effective_date(str(p)) is None
