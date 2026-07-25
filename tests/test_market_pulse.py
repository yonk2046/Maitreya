"""Tests for tools/fetch_market_pulse.py — market breadth parser + WORM archive.

Covers Phase 1 第 2 線 (母體修正, 判例 #41):
  - `_parse_breadth_cell`: strict composite-string parsing ("411(22)" / "74"),
    and loud failure (raises, never coerces to 0) on garbage input.
  - `_fetch_market_breadth`: end-to-end table lookup against a fake TWSE
    response, including the "股票" vs "整體市場" column distinction and
    partial-parse-failure reporting via the `error` key.
  - `fetch_and_write`: per-date archive under data/market_pulse/YYYY-MM-DD.json
    is write-once (WORM) — a second run for the same date must not overwrite
    an existing archive file, while data/market_pulse.json (latest) is always
    refreshed.

Run:
    cd "Ai stock" && python -m pytest tests/test_market_pulse.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))
_TOOLS = _AI_STOCK / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import fetch_market_pulse as fmp  # noqa: E402


# ── _parse_breadth_cell ───────────────────────────────────────────────────────

def test_parse_composite_cell_with_limit_subset():
    count, sub = fmp._parse_breadth_cell("411(22)")
    assert count == 411
    assert sub == 22


def test_parse_composite_cell_with_thousands_separator():
    count, sub = fmp._parse_breadth_cell("5,597(133)")
    assert count == 5597
    assert sub == 133


def test_parse_bare_number_no_parenthesis():
    count, sub = fmp._parse_breadth_cell("74")
    assert count == 74
    assert sub is None


def test_parse_bare_zero():
    count, sub = fmp._parse_breadth_cell("0")
    assert count == 0
    assert sub is None


def test_parse_cell_strips_whitespace():
    count, sub = fmp._parse_breadth_cell("  411(22)  ")
    assert count == 411
    assert sub == 22


@pytest.mark.parametrize("garbage", ["", "N/A", "--", "411(", "(22)", "abc(def)", "411(22)(33)"])
def test_parse_garbage_raises_not_zero(garbage):
    # Loud failure — must raise, never silently return (0, None).
    with pytest.raises(ValueError, match="cannot parse breadth cell"):
        fmp._parse_breadth_cell(garbage)


# ── _fetch_market_breadth ─────────────────────────────────────────────────────

def _fake_allbut0999_response(stock_col=None, extra_tables=True):
    """Build a fake TWSE MI_INDEX?type=ALLBUT0999 response.

    stock_col overrides the 5 values in the 股票 column of 漲跌證券數合計
    (advancers, decliners, unchanged, unmatched, no_comparison cells, in
    that row order) — defaults to the spike's real 2026-07-09 numbers.
    """
    if stock_col is None:
        stock_col = ["411(22)", "552(2)", "74", "0", "41"]
    rows = [
        ["上漲(漲停)", "5,597(133)", stock_col[0]],
        ["下跌(跌停)", "4,719(128)", stock_col[1]],
        ["持平",       "814",        stock_col[2]],
        ["未成交",     "16,359",     stock_col[3]],
        ["無比價",     "3,094",      stock_col[4]],
    ]
    tables = []
    if extra_tables:
        tables.append({"title": "115年07月09日 大盤統計資訊", "fields": [], "data": []})
    tables.append({
        "title": "漲跌證券數合計",
        "fields": ["類型", "整體市場", "股票"],
        "data": rows,
    })
    return {"stat": "OK", "tables": tables}


def test_fetch_market_breadth_happy_path(monkeypatch):
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: _fake_allbut0999_response())
    out = fmp._fetch_market_breadth("20260709")
    assert "error" not in out
    assert out["universe"] == "twse_listed_stocks"
    assert out["source"] == "twse-MI_INDEX-ALLBUT0999"
    assert out["advancers"] == 411
    assert out["advancers_limit_up"] == 22
    assert out["decliners"] == 552
    assert out["decliners_limit_down"] == 2
    assert out["unchanged"] == 74
    assert out["unmatched"] == 0
    assert out["no_comparison"] == 41
    assert out["total"] == 411 + 552 + 74 + 0 + 41 == 1078


def test_fetch_market_breadth_uses_stock_column_not_overall_market(monkeypatch):
    # The 整體市場 column deliberately has different (larger) numbers; make
    # sure we never accidentally read it — that's the whole point of #41.
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: _fake_allbut0999_response())
    out = fmp._fetch_market_breadth("20260709")
    assert out["advancers"] != 5597
    assert out["decliners"] != 4719


def test_fetch_market_breadth_missing_table_reports_error(monkeypatch):
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "OK", "tables": []})
    out = fmp._fetch_market_breadth("20260709")
    assert "error" in out
    assert "漲跌證券數合計" in out["error"]
    assert out["universe"] == "twse_listed_stocks"  # scope still declared even on failure


def test_fetch_market_breadth_bad_stat_reports_error(monkeypatch):
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "查無資料"})
    out = fmp._fetch_market_breadth("20260709")
    assert "error" in out
    assert "查無資料" in out["error"]


def test_fetch_market_breadth_request_exception_reports_error(monkeypatch):
    def _boom(*a, **k):
        raise TimeoutError("connection timed out")
    monkeypatch.setattr(fmp, "_get_json", _boom)
    out = fmp._fetch_market_breadth("20260709")
    assert "error" in out
    assert "connection timed out" in out["error"]


def test_fetch_market_breadth_composite_parse_failure_does_not_fabricate_zero(monkeypatch):
    # One garbled cell ("N/A" for advancers) must surface as `error`, and the
    # function must NOT return advancers=0 as if that were a real reading.
    bad_col = ["N/A", "552(2)", "74", "0", "41"]
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: _fake_allbut0999_response(stock_col=bad_col))
    out = fmp._fetch_market_breadth("20260709")
    assert "error" in out
    assert "cannot parse breadth cell" in out["error"]
    assert out.get("advancers") != 0
    assert "advancers" not in out  # failed field must be absent, not zeroed
    assert "total" not in out      # partial data must not be summed into a total


def test_fetch_market_breadth_missing_row_reports_error(monkeypatch):
    resp = _fake_allbut0999_response()
    # Drop the 持平 row entirely.
    resp["tables"][-1]["data"] = [r for r in resp["tables"][-1]["data"] if r[0] != "持平"]
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: resp)
    out = fmp._fetch_market_breadth("20260709")
    assert "error" in out
    assert "持平" in out["error"]


# ── fetch_and_write — per-date WORM archive ──────────────────────────────────

def _stub_fetchers(monkeypatch, breadth_col=None):
    """Stub out every network-touching sub-fetcher so fetch_and_write is offline."""
    monkeypatch.setattr(fmp, "_fetch_taiex", lambda date_str=None: {
        "close": 22150.23, "change": 125.45, "change_pct": 0.57,
        "volume_b_ntd": None, "source": "twse-MI_INDEX-tables",
    })
    monkeypatch.setattr(fmp, "_fetch_tx_futures", lambda date_str=None: {
        "close": 22180, "change": 130, "open_interest": 62150,
        "oi_change": 1240, "volume": 85234, "source": "taifex-openapi",
    })
    monkeypatch.setattr(fmp, "_fetch_institutional_futures", lambda date_str=None: {
        "foreign": {"net_oi": 25431, "oi_change": 1240},
        "source": "taifex-openapi",
    })
    monkeypatch.setattr(
        fmp, "_get_json",
        lambda *a, **k: _fake_allbut0999_response(stock_col=breadth_col),
    )


def test_archive_writes_per_date_file(tmp_path, monkeypatch):
    _stub_fetchers(monkeypatch)
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    pulse = fmp.fetch_and_write(
        dry_run=False, date_str="2026-07-09",
        out_path=out_path, archive_dir=archive_dir,
    )

    assert out_path.exists()
    archive_path = archive_dir / "2026-07-09.json"
    assert archive_path.exists()
    archived = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archived["date"] == "2026-07-09"
    assert archived["breadth"]["advancers"] == 411
    assert pulse["breadth"]["advancers"] == 411


def test_archive_is_worm_does_not_overwrite(tmp_path, monkeypatch):
    _stub_fetchers(monkeypatch, breadth_col=["411(22)", "552(2)", "74", "0", "41"])
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    fmp.fetch_and_write(
        dry_run=False, date_str="2026-07-09",
        out_path=out_path, archive_dir=archive_dir,
    )
    archive_path = archive_dir / "2026-07-09.json"
    first_write_mtime = archive_path.stat().st_mtime_ns
    first_content = archive_path.read_text(encoding="utf-8")

    # Re-run for the same date with materially different upstream numbers —
    # simulates a re-fetch/backfill after the day's archive already exists.
    _stub_fetchers(monkeypatch, breadth_col=["999(0)", "1(0)", "5", "0", "0"])
    fmp.fetch_and_write(
        dry_run=False, date_str="2026-07-09",
        out_path=out_path, archive_dir=archive_dir,
    )

    # Archive must be untouched (WORM); market_pulse.json (latest) DOES update.
    assert archive_path.read_text(encoding="utf-8") == first_content
    assert archive_path.stat().st_mtime_ns == first_write_mtime
    latest = json.loads(out_path.read_text(encoding="utf-8"))
    assert latest["breadth"]["advancers"] == 999


def test_archive_different_dates_both_written(tmp_path, monkeypatch):
    _stub_fetchers(monkeypatch)
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    fmp.fetch_and_write(dry_run=False, date_str="2026-07-08", out_path=out_path, archive_dir=archive_dir)
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-09", out_path=out_path, archive_dir=archive_dir)

    assert (archive_dir / "2026-07-08.json").exists()
    assert (archive_dir / "2026-07-09.json").exists()


def test_dry_run_does_not_write_archive(tmp_path, monkeypatch):
    _stub_fetchers(monkeypatch)
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    fmp.fetch_and_write(dry_run=True, date_str="2026-07-09", out_path=out_path, archive_dir=archive_dir)

    assert not out_path.exists()
    assert not archive_dir.exists()


def test_breadth_error_recorded_in_top_level_errors(tmp_path, monkeypatch):
    _stub_fetchers(monkeypatch)
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "查無資料"})
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    pulse = fmp.fetch_and_write(
        dry_run=False, date_str="2026-07-09",
        out_path=out_path, archive_dir=archive_dir,
    )

    assert any(e.startswith("breadth:") for e in pulse["errors"])
    assert "error" in pulse["breadth"]


# ── _pulse_has_error / archive error→clean upgrade (2026-07-14 事故後修法) ────
#
# 事故:11:46 盤中補跑打到 TWSE MI_INDEX 拿到「很抱歉，沒有符合條件的資料！」,
# 帶 error 的 breadth 被舊版純 WORM 規則寫死進 per-date 檔,傍晚正常抓取被擋住
# 不能覆寫。新規則:WORM 只保護「乾淨」檔案;帶 error 的既有檔案可被之後的
# 乾淨抓取升級覆寫。

def test_pulse_has_error_true_for_nonempty_errors_list():
    pulse = {"errors": ["taiex: request failed"], "breadth": {"total": 1078}}
    assert fmp._pulse_has_error(pulse) is True


def test_pulse_has_error_true_for_breadth_error_key():
    pulse = {"errors": [], "breadth": {"error": "stat != OK: '查無資料'"}}
    assert fmp._pulse_has_error(pulse) is True


def test_pulse_has_error_false_for_clean_pulse():
    pulse = {"errors": [], "breadth": {"total": 1078, "advancers": 411}}
    assert fmp._pulse_has_error(pulse) is False


def test_archive_upgrades_from_error_to_clean(tmp_path, monkeypatch):
    """既有檔帶 error,新 fetch 乾淨 → 允許覆寫(error→clean upgrade)。"""
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    # First run: breadth fetch errors out — per-date archive records the
    # honest failed attempt (empty slot → always written).
    _stub_fetchers(monkeypatch)
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "查無資料"})
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-14", out_path=out_path, archive_dir=archive_dir)
    archive_path = archive_dir / "2026-07-14.json"
    assert "error" in json.loads(archive_path.read_text(encoding="utf-8"))["breadth"]

    # Second run (later the same day, post-close): breadth fetch succeeds.
    _stub_fetchers(monkeypatch)
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-14", out_path=out_path, archive_dir=archive_dir)

    upgraded = json.loads(archive_path.read_text(encoding="utf-8"))
    assert "error" not in upgraded["breadth"]
    assert upgraded["breadth"]["advancers"] == 411
    assert upgraded["errors"] == []


def test_archive_clean_not_overwritten_by_later_error(tmp_path, monkeypatch):
    """既有檔乾淨,新 fetch 帶 error → 不覆寫(WORM 維持,絕不讓乾淨檔被錯誤結果沖掉)。"""
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    _stub_fetchers(monkeypatch)
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-14", out_path=out_path, archive_dir=archive_dir)
    archive_path = archive_dir / "2026-07-14.json"
    clean_content = archive_path.read_text(encoding="utf-8")

    _stub_fetchers(monkeypatch)
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "查無資料"})
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-14", out_path=out_path, archive_dir=archive_dir)

    assert archive_path.read_text(encoding="utf-8") == clean_content
    still_clean = json.loads(archive_path.read_text(encoding="utf-8"))
    assert "error" not in still_clean["breadth"]


def test_archive_error_not_overwritten_by_another_error(tmp_path, monkeypatch):
    """既有檔帶 error,新 fetch 也帶 error → 維持既有(已誠實記錄過一次嘗試)。"""
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    _stub_fetchers(monkeypatch)
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "查無資料 (first)"})
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-14", out_path=out_path, archive_dir=archive_dir)
    archive_path = archive_dir / "2026-07-14.json"
    first_error_content = archive_path.read_text(encoding="utf-8")

    _stub_fetchers(monkeypatch)
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "查無資料 (second)"})
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-14", out_path=out_path, archive_dir=archive_dir)

    assert archive_path.read_text(encoding="utf-8") == first_error_content


# ── latest pointer 降級不覆寫 (2026-07-25 事故後修法) ────────────────────────
#
# 事故:週六 11:52 late-cron 三個來源全 error、taiex 退回 cache,卻照樣覆寫掉
# data/market_pulse.json 裡前一日真實的 43654.84 (−2.67%) → 看板「現在大盤」
# 被無聲降級成隔夜快取值。修法:只有 fresh 結果能覆寫 latest pointer。

def test_latest_pointer_not_overwritten_by_errored_fetch(tmp_path, monkeypatch):
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    # 交易日:乾淨抓取 → pointer 寫入真值。
    _stub_fetchers(monkeypatch)
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-24", out_path=out_path, archive_dir=archive_dir)
    good = out_path.read_text(encoding="utf-8")
    assert json.loads(good)["taiex"]["close"] == 22150.23

    # 隔天(週六)late-cron:taiex 退回 cache + breadth error。
    _stub_fetchers(monkeypatch)
    monkeypatch.setattr(fmp, "_fetch_taiex", lambda date_str=None: {
        "close": 22150.23, "change": 125.45, "change_pct": 0.57,
        "volume_b_ntd": None, "source": "twse-MI_INDEX-tables (cached)",
    })
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "很抱歉，沒有符合條件的資料!"})
    pulse = fmp.fetch_and_write(dry_run=False, date_str="2026-07-25", out_path=out_path, archive_dir=archive_dir)

    # Pointer 逐 byte 不動;但當日 per-date 檔仍誠實記錄這次降級嘗試。
    assert out_path.read_text(encoding="utf-8") == good
    assert pulse["errors"]
    assert (archive_dir / "2026-07-25.json").exists()


def test_latest_pointer_abstains_on_cached_taiex_even_without_errors(tmp_path, monkeypatch):
    """Partial/cached 也 abstain — errors 空但 taiex 來自 cache 不算 fresh。"""
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    _stub_fetchers(monkeypatch)
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-24", out_path=out_path, archive_dir=archive_dir)
    good = out_path.read_text(encoding="utf-8")

    _stub_fetchers(monkeypatch)
    monkeypatch.setattr(fmp, "_fetch_taiex", lambda date_str=None: {
        "close": 22150.23, "change": 125.45, "change_pct": 0.57,
        "volume_b_ntd": None, "source": "twse-MI_INDEX-tables (cached)",
    })
    pulse = fmp.fetch_and_write(dry_run=False, date_str="2026-07-25", out_path=out_path, archive_dir=archive_dir)

    assert pulse["errors"] == []          # 沒有 error,但仍不夠新鮮
    assert out_path.read_text(encoding="utf-8") == good


def test_latest_pointer_bootstrap_writes_when_absent(tmp_path, monkeypatch):
    """沒有既有 pointer 時,降級結果照寫(看板需要有檔;errors[] 自述降級)。"""
    out_path = tmp_path / "market_pulse.json"
    archive_dir = tmp_path / "market_pulse"

    _stub_fetchers(monkeypatch)
    monkeypatch.setattr(fmp, "_get_json", lambda *a, **k: {"stat": "查無資料"})
    fmp.fetch_and_write(dry_run=False, date_str="2026-07-25", out_path=out_path, archive_dir=archive_dir)

    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8"))["errors"]


# ── TAIFEX CSV fallback honours --date (歷史回補不吃 now()) — 2026-07-16/17 事故 ──
# 根因:_fetch_*_futures_html 的 fallback 寫死 qdate = now(),忽略傳入日期 →
# 歷史回補靜默抓成「今天」的期貨/三大法人資料。修法:_html 版吃 date_str。

def _capture_csv_url(monkeypatch):
    """Monkeypatch _get_csv to record the URL(s) it is asked to fetch, and
    return empty rows so the caller falls through to its 'not found' branch."""
    seen: list[str] = []

    def fake_get_csv(url, timeout=15):
        seen.append(url)
        return []

    monkeypatch.setattr(fmp, "_get_csv", fake_get_csv)
    return seen


def test_tx_futures_html_fallback_uses_passed_date_not_now(monkeypatch):
    seen = _capture_csv_url(monkeypatch)
    fmp._fetch_tx_futures_html("2026-07-16")
    assert seen, "expected _get_csv to be called"
    assert all("2026/07/16" in u for u in seen)
    today = fmp.datetime.now(fmp.TW_TZ).strftime("%Y/%m/%d")
    if today != "2026/07/16":
        assert not any(today in u for u in seen)


def test_institutional_futures_html_fallback_uses_passed_date_not_now(monkeypatch):
    seen = _capture_csv_url(monkeypatch)
    fmp._fetch_institutional_futures_html("2026-07-16")
    assert seen, "expected _get_csv to be called"
    assert all("2026/07/16" in u for u in seen)
    today = fmp.datetime.now(fmp.TW_TZ).strftime("%Y/%m/%d")
    if today != "2026/07/16":
        assert not any(today in u for u in seen)


def test_html_fallback_none_date_keeps_now_behaviour(monkeypatch):
    seen = _capture_csv_url(monkeypatch)
    fmp._fetch_tx_futures_html(None)
    today = fmp.datetime.now(fmp.TW_TZ).strftime("%Y/%m/%d")
    assert seen and all(today in u for u in seen)


# ── TAIEX MI_INDEX 漲跌符號 — 2026-07-17 事故 ───────────────────────────────
# 根因:TWSE MI_INDEX 欄位順序是 指數,收盤指數,漲跌(+/-),漲跌點數,漲跌百分比(%)。
# 「漲跌點數」(row[3]) 是不帶正負號的絕對值,正負號在獨立的 row[2]
# (HTML 包裹,如 "<p style='color:green'>-</p>")。舊碼直接把 row[3] 當成已簽章
# 的 change,大跌日因此輸出正值(收盤 42671.27、change_pct=-6.47,
# 但 change 誤植為 +2953.71,對照 data/market_pulse/2026-07-17.json)。

def _fake_mi_index_ind_response(title, sign_html, mag, pct):
    return {
        "stat": "OK",
        "tables": [{
            "title": title,
            "fields": ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "特殊處理註記"],
            "data": [
                ["發行量加權股價指數", "42,671.27" if mag == "2,953.71" else "22,150.23",
                 sign_html, mag, pct, ""],
            ],
        }],
    }


def _block_taiex_network_and_cache(monkeypatch):
    """Force the Yahoo step to fail fast (no network in tests) so _fetch_taiex
    falls through to the MI_INDEX-tables step, and stop it writing to the
    real data/.taiex_cache.json (data/ is WORM/off-limits for this task)."""
    monkeypatch.setattr(fmp.time, "sleep", lambda *_: None)

    def _no_network(*a, **k):
        raise OSError("network disabled in test")
    monkeypatch.setattr(fmp.urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(fmp, "_save_taiex_cache", lambda *_a, **_k: None)


def test_fetch_taiex_mi_index_down_day_change_matches_change_pct_sign(monkeypatch):
    _block_taiex_network_and_cache(monkeypatch)
    monkeypatch.setattr(
        fmp, "_get_json",
        lambda *a, **k: _fake_mi_index_ind_response(
            "115年07月17日 價格指數(臺灣證券交易所)",
            "<p style ='color:green'>-</p>", "2,953.71", "-6.47",
        ),
    )
    out = fmp._fetch_taiex("20260717")
    assert out["source"] == "twse-MI_INDEX-tables"
    assert out["close"] == 42671.27
    assert out["change_pct"] == -6.47
    assert out["change"] == -2953.71   # was +2953.71 before the fix


def test_fetch_taiex_mi_index_up_day_change_stays_positive(monkeypatch):
    _block_taiex_network_and_cache(monkeypatch)
    monkeypatch.setattr(
        fmp, "_get_json",
        lambda *a, **k: _fake_mi_index_ind_response(
            "價格指數(臺灣證券交易所)",
            "<p style ='color:red'>+</p>", "125.45", "0.57",
        ),
    )
    out = fmp._fetch_taiex("20260601")
    assert out["close"] == 22150.23
    assert out["change_pct"] == 0.57
    assert out["change"] == 125.45


def test_fetch_taiex_mi_index_missing_sign_falls_back_to_pct_sign(monkeypatch):
    """If the +/- column is ever unparseable, still trust the already-signed
    change_pct column from the same row rather than defaulting positive."""
    _block_taiex_network_and_cache(monkeypatch)

    def fake_get_json(*a, **k):
        return {
            "stat": "OK",
            "tables": [{
                "title": "價格指數(臺灣證券交易所)",
                "fields": ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "特殊處理註記"],
                "data": [["發行量加權股價指數", "42,671.27", "", "2,953.71", "-6.47", ""]],
            }],
        }
    monkeypatch.setattr(fmp, "_get_json", fake_get_json)
    out = fmp._fetch_taiex("20260717")
    assert out["change"] == -2953.71
