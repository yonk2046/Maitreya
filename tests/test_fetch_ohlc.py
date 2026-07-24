"""Tests for tools/fetch_ohlc.py — TWSE STOCK_DAY OHLC 回填(Wave C2)。

不打真網路:所有測試以 monkeypatch 假造 get_json_fn/sleep_fn,或直接餵入
canned TWSE STOCK_DAY 回應樣本驗證純函數解析。裁定 R3 紅線:本卡只驗證採集
工具本身(解析/檔案結構/斷點續抓/節流),不涉及 core/schema/ingest。
"""
from __future__ import annotations

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools.fetch_ohlc import (  # noqa: E402
    BACKFILL_START,
    MIN_SLEEP_SEC,
    build_ticker_days,
    discover_universe,
    fetch_month_raw,
    month_list,
    parse_stock_day,
    run,
    write_ticker_file,
)

# ── Canned TWSE STOCK_DAY response ───────────────────────────────────────────
# 欄位順序:日期(民國) 成交股數 成交金額 開盤價 最高價 最低價 收盤價 漲跌價差 成交筆數

_RAW_OK = {
    "stat": "OK",
    "data": [
        ["115/07/01", "12,345,678", "1,234,567,890", "838.00", "845.00", "835.00", "840.00", "+2.00", "12345"],
        ["115/07/02", "9,876,543", "987,654,321", "840.00", "848.00", "838.00", "845.00", "+5.00", "9876"],
        # 跌停/一字盤等情況 TWSE 常用 "X0.00" 或 "--" 表示無法計算的欄位
        ["115/07/03", "1,000", "10,000", "845.00", "845.00", "845.00", "845.00", "X0.00", "10"],
    ],
}

_RAW_NOT_OK = {"stat": "很抱歉，沒有符合條件的資料！"}


# ── parse_stock_day ──────────────────────────────────────────────────────────

def test_parse_stock_day_basic_fields():
    days = parse_stock_day(_RAW_OK)
    assert set(days.keys()) == {"2026-07-01", "2026-07-02", "2026-07-03"}
    d1 = days["2026-07-01"]
    assert d1["open"] == 838.0
    assert d1["high"] == 845.0
    assert d1["low"] == 835.0
    assert d1["close"] == 840.0
    assert d1["volume"] == 12345678
    assert d1["source"] == "twse-STOCK_DAY"


def test_parse_stock_day_handles_unparseable_change_gracefully():
    # row 3's chg="X0.00" isn't consumed by parse_stock_day (only open/high/low/
    # close/volume are extracted) — the row must still parse cleanly.
    days = parse_stock_day(_RAW_OK)
    assert days["2026-07-03"]["close"] == 845.0


def test_parse_stock_day_not_ok_returns_empty():
    assert parse_stock_day(_RAW_NOT_OK) == {}


def test_parse_stock_day_missing_data_key_returns_empty():
    assert parse_stock_day({"stat": "OK"}) == {}


def test_parse_stock_day_short_rows_skipped():
    raw = {"stat": "OK", "data": [["115/07/01", "1", "2"]]}  # too few columns
    assert parse_stock_day(raw) == {}


# ── month_list ────────────────────────────────────────────────────────────────

def test_month_list_spans_inclusive():
    assert month_list("2026-05-08", "2026-07-24") == ["202605", "202606", "202607"]


def test_month_list_single_month():
    assert month_list("2026-07-01", "2026-07-24") == ["202607"]


def test_month_list_year_rollover():
    assert month_list("2025-11-15", "2026-02-03") == ["202511", "202512", "202601", "202602"]


def test_month_list_empty_when_to_before_from():
    assert month_list("2026-07-24", "2026-05-08") == []


# ── discover_universe ────────────────────────────────────────────────────────

def _write_report(reports_dir: pathlib.Path, date: str, tickers: list[str]) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {"date": date, "stocks": [{"ticker": t, "name": f"股{t}"} for t in tickers]}
    (reports_dir / f"{date}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_discover_universe_unions_across_dates(tmp_path):
    reports_dir = tmp_path / "reports"
    _write_report(reports_dir, "2026-05-08", ["2330", "2317"])
    _write_report(reports_dir, "2026-05-09", ["2330", "2002"])
    out = discover_universe(reports_dir, since_date="2026-05-08", include_tier_a=False)
    assert out == {"2330", "2317", "2002"}


def test_discover_universe_respects_since_date(tmp_path):
    reports_dir = tmp_path / "reports"
    _write_report(reports_dir, "2026-04-30", ["9999"])   # before since_date, excluded
    _write_report(reports_dir, "2026-05-08", ["2330"])
    out = discover_universe(reports_dir, since_date="2026-05-08", include_tier_a=False)
    assert out == {"2330"}
    assert "9999" not in out


def test_discover_universe_filters_non_4digit_tickers(tmp_path):
    # 已知上游瑕疵:ticker 欄位偶爾混碼(如 "3673TPK"),需被排除,不當成正常股票抓取
    reports_dir = tmp_path / "reports"
    _write_report(reports_dir, "2026-05-08", ["2330", "3673TPK", "6456GIS", "02001R"])
    out = discover_universe(reports_dir, since_date="2026-05-08", include_tier_a=False)
    assert out == {"2330"}


def test_discover_universe_ignores_sidecar_and_example_files(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    _write_report(reports_dir, "2026-05-08", ["2330"])
    # sidecar variants that must NOT be scanned as if they were plain daily reports
    (reports_dir / "2026-05-08.json.sha256").write_text("deadbeef", encoding="utf-8")
    (reports_dir / "2026-05-22.example.json").write_text(
        json.dumps({"stocks": [{"ticker": "8888"}]}), encoding="utf-8"
    )
    (reports_dir / "2026-05-22.intelligence.json").write_text(
        json.dumps({"stocks": [{"ticker": "7777"}]}), encoding="utf-8"
    )
    out = discover_universe(reports_dir, since_date="2026-05-08", include_tier_a=False)
    assert out == {"2330"}


def test_discover_universe_includes_tier_a_by_default(tmp_path):
    reports_dir = tmp_path / "reports"
    _write_report(reports_dir, "2026-05-08", ["9999"])
    out = discover_universe(reports_dir, since_date="2026-05-08")
    assert "9999" in out
    assert "2330" in out  # TIER_A anchor, present even though absent from snapshots


def test_discover_universe_missing_dir_returns_empty_without_tier_a(tmp_path):
    out = discover_universe(tmp_path / "nope", since_date="2026-05-08", include_tier_a=False)
    assert out == set()


# ── fetch_month_raw: cache + throttle ────────────────────────────────────────

def test_fetch_month_raw_cache_miss_calls_network_and_sleeps(tmp_path):
    calls = {"get_json": 0, "sleep": []}

    def fake_get_json(url):
        calls["get_json"] += 1
        assert "stockNo=2330" in url and "date=20260701" in url
        return _RAW_OK

    def fake_sleep(s):
        calls["sleep"].append(s)

    raw = fetch_month_raw(
        "2330", "202607",
        raw_cache_dir=tmp_path, sleep_s=2.0,
        get_json_fn=fake_get_json, sleep_fn=fake_sleep,
    )
    assert raw == _RAW_OK
    assert calls["get_json"] == 1
    assert calls["sleep"] == [2.0]
    assert (tmp_path / "2330_202607.json").is_file()


def test_fetch_month_raw_cache_hit_skips_network_and_sleep(tmp_path):
    cache_file = tmp_path / "2330_202607.json"
    cache_file.write_text(json.dumps(_RAW_OK), encoding="utf-8")

    def fail_get_json(url):
        raise AssertionError("must not hit network on cache hit")

    def fail_sleep(s):
        raise AssertionError("must not sleep on cache hit")

    raw = fetch_month_raw(
        "2330", "202607",
        raw_cache_dir=tmp_path, get_json_fn=fail_get_json, sleep_fn=fail_sleep,
    )
    assert raw == _RAW_OK


def test_fetch_month_raw_enforces_sleep_floor(tmp_path):
    calls = {"sleep": []}
    fetch_month_raw(
        "2330", "202607",
        raw_cache_dir=tmp_path, sleep_s=0.001,   # attempt to lower below floor
        get_json_fn=lambda url: _RAW_OK, sleep_fn=lambda s: calls["sleep"].append(s),
    )
    assert calls["sleep"] == [MIN_SLEEP_SEC]
    assert MIN_SLEEP_SEC >= 2.0


# ── build_ticker_days: multi-month merge + resilience ───────────────────────

def test_build_ticker_days_merges_months(tmp_path):
    def fake_get_json(url):
        if "date=20260601" in url:
            return {"stat": "OK", "data": [
                ["115/06/01", "1", "1", "10", "11", "9", "10.5", "+0.5", "1"],
            ]}
        return _RAW_OK  # 202607

    days = build_ticker_days(
        "2330", ["202606", "202607"],
        raw_cache_dir=tmp_path, get_json_fn=fake_get_json, sleep_fn=lambda s: None,
    )
    assert "2026-06-01" in days
    assert "2026-07-01" in days
    assert len(days) == 4


def test_build_ticker_days_continues_after_one_month_fails(tmp_path):
    calls = {"n": 0}

    def flaky_get_json(url):
        calls["n"] += 1
        if "date=20260601" in url:
            raise TimeoutError("simulated network failure")
        return _RAW_OK

    logged = []
    days = build_ticker_days(
        "2330", ["202606", "202607"],
        raw_cache_dir=tmp_path, get_json_fn=flaky_get_json, sleep_fn=lambda s: None,
        log_fn=logged.append,
    )
    # 202606 failed entirely (no partial rows), 202607 succeeded
    assert "2026-07-01" in days
    assert not any(d.startswith("2026-06") for d in days)
    assert any("2330" in msg and "202606" in msg for msg in logged)


# ── write_ticker_file: merge-not-overwrite ──────────────────────────────────

def test_write_ticker_file_creates_expected_shape(tmp_path):
    days = {"2026-07-01": {"open": 1, "high": 2, "low": 0.5, "close": 1.5,
                            "volume": 100, "source": "twse-STOCK_DAY"}}
    out_path = write_ticker_file("2330", days, out_dir=tmp_path)
    assert out_path == tmp_path / "2330.json"
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["ticker"] == "2330"
    assert payload["source"] == "twse-STOCK_DAY"
    assert "generated_at" in payload
    assert payload["days"] == days


def test_write_ticker_file_merges_with_existing_not_clobbers(tmp_path):
    write_ticker_file("2330", {"2026-05-08": {"close": 1.0}}, out_dir=tmp_path)
    write_ticker_file("2330", {"2026-05-09": {"close": 2.0}}, out_dir=tmp_path)
    payload = json.loads((tmp_path / "2330.json").read_text(encoding="utf-8"))
    assert set(payload["days"].keys()) == {"2026-05-08", "2026-05-09"}


def test_write_ticker_file_new_data_wins_on_same_date(tmp_path):
    write_ticker_file("2330", {"2026-05-08": {"close": 1.0}}, out_dir=tmp_path)
    write_ticker_file("2330", {"2026-05-08": {"close": 999.0}}, out_dir=tmp_path)
    payload = json.loads((tmp_path / "2330.json").read_text(encoding="utf-8"))
    assert payload["days"]["2026-05-08"]["close"] == 999.0


# ── run(): end-to-end orchestration ──────────────────────────────────────────

def test_run_dry_run_does_not_write_or_call_network(tmp_path):
    def fail_get_json(url):
        raise AssertionError("dry-run must not hit network")

    out_dir = tmp_path / "ohlc"
    stats = run(
        ["2330", "2317"], "2026-07-01", "2026-07-24",
        dry_run=True, raw_cache_dir=tmp_path / "cache", out_dir=out_dir,
        get_json_fn=fail_get_json, sleep_fn=lambda s: None, log_fn=lambda s: None,
    )
    assert stats["written"] == 0
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_run_writes_one_file_per_ticker(tmp_path):
    stats = run(
        ["2330", "2317"], "2026-07-01", "2026-07-24",
        raw_cache_dir=tmp_path / "cache", out_dir=tmp_path / "ohlc",
        get_json_fn=lambda url: _RAW_OK, sleep_fn=lambda s: None, log_fn=lambda s: None,
    )
    assert stats["written"] == 2
    assert (tmp_path / "ohlc" / "2330.json").is_file()
    assert (tmp_path / "ohlc" / "2317.json").is_file()
    assert stats["days"] == 6  # 3 days × 2 tickers


def test_run_resume_skips_cached_network_calls(tmp_path):
    cache_dir = tmp_path / "cache"
    out_dir = tmp_path / "ohlc"
    calls = {"n": 0}

    def counting_get_json(url):
        calls["n"] += 1
        return _RAW_OK

    run(["2330"], "2026-07-01", "2026-07-24",
        raw_cache_dir=cache_dir, out_dir=out_dir,
        get_json_fn=counting_get_json, sleep_fn=lambda s: None, log_fn=lambda s: None)
    assert calls["n"] == 1

    # second run over the same range must hit the cache, not the network
    run(["2330"], "2026-07-01", "2026-07-24",
        raw_cache_dir=cache_dir, out_dir=out_dir,
        get_json_fn=counting_get_json, sleep_fn=lambda s: None, log_fn=lambda s: None)
    assert calls["n"] == 1


def test_backfill_start_constant_matches_snapshot_arc():
    # R3/清單 4.4:OHLC 回填期間對齊回測弧快照起點(fable 裁定書 §一 R3)
    assert BACKFILL_START == "2026-05-08"
