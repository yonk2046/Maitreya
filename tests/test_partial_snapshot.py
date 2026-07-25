"""兩段式快照 (2026-07-07, schema 1.8.1).

Mac 關機夜: 雲端 20:00 晚班建「部分快照」(價格+分點, T86 不可得 →
fii_pending=True), 早晨班次 T86 到手後 supersede 重建補完。

Covers:
  - adapter 層鐵律: t86Date != date → 滯後 T86 整組丟棄 + fii_pending
  - fii_pending 隨 adapter → ingest 進快照頂層
  - daily._snapshot_is_partial: 補完路徑的判定
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
_TOOLS = _AI_STOCK / "tools"
for p in (_AI_STOCK, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from data.adapters.legacy import adapt_legacy  # noqa: E402
from tools import daily                        # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────

_BASE_TODAY = {
    "tradingDate": "2026-07-07",
    "mainForceBuy": [
        {"code": "2303", "name": "聯電", "rank": 1, "close": 169.0,
         "chgPct": 2.74, "buyVol": 5000},
    ],
}


def _adapt(tmp_path, today_payload):
    (tmp_path / "branches").mkdir(exist_ok=True)
    today_json = tmp_path / "today.json"
    today_json.write_text(json.dumps(today_payload), encoding="utf-8")
    return adapt_legacy(paths_override={
        "root":         tmp_path,
        "today_json":   today_json,
        "branches_dir": tmp_path / "branches",
    })


# ── adapter 鐵律: 滯後 T86 丟棄 + fii_pending ───────────────────────────────

def test_adapter_fresh_t86_not_pending(tmp_path):
    out = _adapt(tmp_path, {**_BASE_TODAY, "t86Date": "20260707",
                            "t86": {"2303": {"foreign": 35293}}})
    assert out["fii_pending"] is False
    assert out["raw_inputs_per_ticker"]["2303"]["fii_net_buy"] == 35293


def test_adapter_stale_t86_dropped_and_pending(tmp_path):
    # 7/03 事故形狀: t86 有資料但屬於前一日 → 整組丟棄, 絕不進快照
    out = _adapt(tmp_path, {**_BASE_TODAY, "t86Date": "20260706",
                            "t86": {"2303": {"foreign": -12538}}})
    assert out["fii_pending"] is True
    assert out["raw_inputs_per_ticker"]["2303"]["fii_net_buy"] is None
    warnings = [e for e in out["audit_events"]
                if e.get("step") == "adapters.legacy.t86"]
    assert len(warnings) == 1 and warnings[0]["event"] == "DATA_WARNING"


def test_adapter_missing_t86_pending(tmp_path):
    # 晚班雲端 partial 形狀: fetch 層已把 T86 清空
    out = _adapt(tmp_path, {**_BASE_TODAY, "t86Date": None, "t86": {}})
    assert out["fii_pending"] is True
    assert out["raw_inputs_per_ticker"]["2303"]["fii_net_buy"] is None


def test_adapter_legacy_today_without_t86date_not_pending(tmp_path):
    # 舊 today.json 無 t86Date → 有 t86 就視為新鮮 (與 fii_gate 同語意)
    out = _adapt(tmp_path, {**_BASE_TODAY, "t86": {"2303": {"foreign": 1}}})
    assert out["fii_pending"] is False


# ── ingest: fii_pending 進快照頂層 ──────────────────────────────────────────

def test_ingest_carries_fii_pending(tmp_path):
    from core.ingest import ingest
    cfg = {"temporal": {"lookback_window_days": 5}}
    out = _adapt(tmp_path, {**_BASE_TODAY, "t86Date": None, "t86": {}})
    snap = ingest(out, cfg, repo_root=str(tmp_path))
    assert snap["fii_pending"] is True

    out2 = _adapt(tmp_path, {**_BASE_TODAY, "t86Date": "20260707",
                             "t86": {"2303": {"foreign": 1}}})
    snap2 = ingest(out2, cfg, repo_root=str(tmp_path))
    assert snap2["fii_pending"] is False


def test_ingest_defaults_false_without_key(tmp_path):
    # rollup/backfill adapter 不帶 fii_pending 鍵 → False
    from core.ingest import ingest
    cfg = {"temporal": {"lookback_window_days": 5}}
    out = _adapt(tmp_path, {**_BASE_TODAY, "t86Date": "20260707",
                            "t86": {"2303": {"foreign": 1}}})
    out.pop("fii_pending")
    snap = ingest(out, cfg, repo_root=str(tmp_path))
    assert snap["fii_pending"] is False


# ── daily._snapshot_is_partial: 補完路徑判定 ────────────────────────────────

@pytest.fixture
def patch_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "REPORTS_DIR", tmp_path)
    def _write(date, payload):
        (tmp_path / f"{date}.json").write_text(json.dumps(payload), encoding="utf-8")
    return _write


def test_partial_snapshot_detected(patch_reports):
    patch_reports("2026-07-07", {"date": "2026-07-07", "fii_pending": True})
    assert daily._snapshot_is_partial("2026-07-07") is True


def test_full_snapshot_not_partial(patch_reports):
    patch_reports("2026-07-07", {"date": "2026-07-07", "fii_pending": False})
    assert daily._snapshot_is_partial("2026-07-07") is False


def test_pre_181_snapshot_not_partial(patch_reports):
    # 1.8.0 以前的快照無 fii_pending 欄位 → 不觸發補完路徑
    patch_reports("2026-07-06", {"date": "2026-07-06"})
    assert daily._snapshot_is_partial("2026-07-06") is False


def test_missing_or_corrupt_snapshot_not_partial(patch_reports, tmp_path):
    assert daily._snapshot_is_partial("2026-01-01") is False
    (tmp_path / "2026-07-07.json").write_text("{not json", encoding="utf-8")
    assert daily._snapshot_is_partial("2026-07-07") is False


# ── run() gate 接線: 晚班 partial / 早晨補完 (mock subprocess, 不跑真 pipeline) ──

from unittest.mock import patch as _patch  # noqa: E402
import subprocess as _subprocess           # noqa: E402


class _FakeProc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.stdout = "ok"
        self.stderr = ""


@pytest.fixture
def flow_env(tmp_path, monkeypatch):
    """auto-daily 路徑 (date=None, skip_fetch=False) 的完整假環境。

    UPSTREAM_FETCH 指向不存在的檔 → fetch 記 skipped 但 gates 照跑
    (與 test_daily.py 的既有慣例一致)。
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(daily, "REPORTS_DIR", reports)
    monkeypatch.setattr(daily, "DAILY_LOGS", tmp_path / "_daily_logs")
    monkeypatch.setattr(daily, "UPSTREAM_FETCH", pathlib.Path("/not/a/real/fetch.py"))
    # Remote-first gate (雲端優先守門) is orthogonal to what these partial-
    # snapshot flow tests verify; simulate an inconclusive remote check
    # (offline) so it fails open to the local flow instead of the blanket
    # subprocess.run mock below making it look like origin/main already has
    # today's report.
    monkeypatch.setattr(daily, "_git_fetch_origin", lambda: False)
    # 盤中守門(09:00-14:00 台北)讀真實牆上時鐘 → 這些 flow 測試在盤中跑就會紅
    # (2026-07-25 上午實測:台北 10:47 執行 `make test` 兩顆必紅)。守門本身有
    # 專屬測試(_intraday_guard_disposition 是純函數),flow 測試不該受執行時刻影響
    # → 把時鐘凍在收盤後,測的才是 partial/supersede 流程本身。
    monkeypatch.setattr(
        daily, "_now_taipei",
        lambda: dt.datetime(2026, 7, 7, 19, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    def _setup(*, latest_snap: dict | None, today: dict):
        if latest_snap:
            (reports / f"{latest_snap['date']}.json").write_text(
                json.dumps(latest_snap), encoding="utf-8")
        tj = tmp_path / "today.json"
        tj.write_text(json.dumps(today), encoding="utf-8")
        monkeypatch.setattr(daily, "TODAY_JSON", tj)

    return _setup


def _run_flow(*, oracle=None, **kw):
    """Drive daily.run with subprocess mocked. `oracle`, if given, replaces the
    trading-day oracle with a fixed (is_open, reason) so flow-level tests don't
    hit the network. Oracle-internal behaviour is covered separately below."""
    steps: list[str] = []

    def fake_run(argv, **_):
        steps.append(" ".join(argv))
        return _FakeProc(0)

    ctx = _patch.object(_subprocess, "run", side_effect=fake_run)
    with ctx:
        if oracle is not None:
            with _patch.object(daily, "_trading_day_oracle", return_value=oracle):
                rc = daily.run(date=None, skip_fetch=False, **kw)
        else:
            rc = daily.run(date=None, skip_fetch=False, **kw)
    return rc, steps


def test_evening_partial_builds_without_t86(flow_env):
    # 情境①: 交易日 + T86 晚到 → partial 照產 (既有行為)。
    # 20:00 晚班: 新交易日、T86 不可得、allow_partial、oracle 確認有開盤 → 建 partial
    flow_env(latest_snap={"date": "2026-07-06", "fii_pending": False},
             today={"tradingDate": "2026-07-07", "t86": {}, "t86Date": None})
    rc, steps = _run_flow(allow_partial=True,
                          oracle=(True, "MI_INDEX stat=OK (test)"))
    assert rc == 0
    assert any("tools.run_pipeline" in s for s in steps), "partial 模式必須建快照"


def test_evening_partial_skips_when_oracle_says_no_session(flow_env):
    # 情境②: 非交易日 (oracle 無資料) → 跳過, 不建殭屍 partial (2026-07-10 事故)。
    flow_env(latest_snap={"date": "2026-07-09", "fii_pending": False},
             today={"tradingDate": "2026-07-10", "t86": {}, "t86Date": None})
    rc, steps = _run_flow(allow_partial=True,
                          oracle=(False, "MI_INDEX stat!=OK — no trading session"))
    assert rc == 0
    assert not any("tools.run_pipeline" in s for s in steps), \
        "放假日必須跳過, 絕不建 partial"


def test_evening_partial_skips_when_oracle_fails_closed(flow_env):
    # 情境③: oracle 網路失敗 → fail-closed 跳過 (寧可少一份, 絕不再產殭屍)。
    flow_env(latest_snap={"date": "2026-07-09", "fii_pending": False},
             today={"tradingDate": "2026-07-10", "t86": {}, "t86Date": None})
    rc, steps = _run_flow(allow_partial=True,
                          oracle=(False, "probe indeterminate — fail-closed"))
    assert rc == 0
    assert not any("tools.run_pipeline" in s for s in steps), \
        "oracle 失敗必須 fail-closed 跳過"


def test_evening_strict_still_skips_without_t86(flow_env):
    # 同情境但 strict (dispatch/早班) → 照舊跳過, 不建
    flow_env(latest_snap={"date": "2026-07-06", "fii_pending": False},
             today={"tradingDate": "2026-07-07", "t86": {}, "t86Date": None})
    rc, steps = _run_flow(allow_partial=False)
    assert rc == 0
    assert not any("tools.run_pipeline" in s for s in steps)


def test_morning_completes_partial_with_fresh_t86(flow_env):
    # 早晨: 昨日 partial 在檔、T86 到手 → 放行重建 (supersede 補完)
    flow_env(latest_snap={"date": "2026-07-07", "fii_pending": True},
             today={"tradingDate": "2026-07-07", "t86Date": "20260707",
                    "t86": {"2303": {"foreign": 35293}}})
    rc, steps = _run_flow(allow_partial=False)
    assert rc == 0
    assert any("tools.run_pipeline" in s for s in steps), "補完路徑必須重建"


def test_morning_partial_but_t86_still_missing_skips(flow_env):
    # partial 在檔但 T86 又沒到 → 留給下一班次, 不重建
    flow_env(latest_snap={"date": "2026-07-07", "fii_pending": True},
             today={"tradingDate": "2026-07-07", "t86": {}, "t86Date": None})
    rc, steps = _run_flow(allow_partial=False)
    assert rc == 0
    assert not any("tools.run_pipeline" in s for s in steps)


def test_full_snapshot_never_rebuilt(flow_env):
    # latest 是完整快照 → 即使 T86 新鮮也不重建 (無 supersede churn)
    flow_env(latest_snap={"date": "2026-07-07", "fii_pending": False},
             today={"tradingDate": "2026-07-07", "t86Date": "20260707",
                    "t86": {"2303": {"foreign": 1}}})
    rc, steps = _run_flow(allow_partial=False)
    assert rc == 0
    assert not any("tools.run_pipeline" in s for s in steps)


# ── 交易日 oracle (MI_INDEX) 內部行為 ────────────────────────────────────────
# 2026-07-10 颱風假殭屍 partial 根因修復: --allow-partial 加獨立於富邦/T86 的
# 「今天有沒有開盤」權威判斷。

@pytest.fixture
def patch_pulse_dir(tmp_path, monkeypatch):
    d = tmp_path / "market_pulse"
    d.mkdir()
    monkeypatch.setattr(daily, "MARKET_PULSE_DIR", d)
    def _write(date, payload):
        (d / f"{date}.json").write_text(json.dumps(payload), encoding="utf-8")
    return _write


def test_oracle_short_circuits_on_local_pulse(patch_pulse_dir):
    # 情境④: 當日 market_pulse 檔已有 parsed breadth → oracle 判 open,
    # 且完全不打 API (短路省一次網路依賴)。
    patch_pulse_dir("2026-07-09", {
        "date": "2026-07-09",
        "breadth": {"advancers": 411, "decliners": 552, "total": 1078},
    })
    with _patch.object(daily, "_mi_index_probe",
                       side_effect=AssertionError("probe must not be called")) as probe:
        is_open, reason = daily._trading_day_oracle("2026-07-09")
    assert is_open is True
    assert "market_pulse archive" in reason
    probe.assert_not_called()


def test_oracle_local_pulse_with_breadth_error_falls_through(patch_pulse_dir):
    # 本地檔 breadth 帶 error (可能是網路/停牌) → 不當 open, 落到 live probe。
    patch_pulse_dir("2026-07-10", {
        "date": "2026-07-10",
        "breadth": {"error": "stat != OK: '很抱歉，沒有符合條件的資料！'"},
    })
    with _patch.object(daily, "_mi_index_probe", return_value=False):
        is_open, reason = daily._trading_day_oracle("2026-07-10")
    assert is_open is False
    assert "MI_INDEX" in reason


def test_oracle_probe_open(patch_pulse_dir):
    # 無本地檔, live probe stat=OK → open。
    with _patch.object(daily, "_mi_index_probe", return_value=True):
        is_open, reason = daily._trading_day_oracle("2026-07-09")
    assert is_open is True
    assert "stat=OK" in reason


def test_oracle_probe_closed(patch_pulse_dir):
    # 情境②: 非交易日, probe stat!=OK → closed。
    with _patch.object(daily, "_mi_index_probe", return_value=False):
        is_open, reason = daily._trading_day_oracle("2026-07-10")
    assert is_open is False
    assert "no trading session" in reason


def test_oracle_probe_indeterminate_fails_closed(patch_pulse_dir):
    # 情境③: probe None (網路錯誤) → fail-closed (is_open False)。
    with _patch.object(daily, "_mi_index_probe", return_value=None):
        is_open, reason = daily._trading_day_oracle("2026-07-10")
    assert is_open is False
    assert "fail-closed" in reason


def test_mi_index_probe_tristate(monkeypatch):
    # _mi_index_probe 對 TWSE 回應的三態解讀 (mock urllib, 不打真 API)。
    import io

    def _fake_urlopen(body):
        class _Resp:
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return lambda *a, **k: _Resp()

    # stat=OK → True (有開盤)
    monkeypatch.setattr(daily.urllib.request, "urlopen",
                        _fake_urlopen(b'{"stat":"OK","tables":[]}'))
    assert daily._mi_index_probe("2026-07-09") is True

    # stat!=OK (放假日) → False
    monkeypatch.setattr(daily.urllib.request, "urlopen",
                        _fake_urlopen('{"stat":"很抱歉，沒有符合條件的資料！"}'.encode("utf-8")))
    assert daily._mi_index_probe("2026-07-10") is False

    # 網路錯誤 → None (fail-closed)
    def _boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(daily.urllib.request, "urlopen", _boom)
    assert daily._mi_index_probe("2026-07-10") is None

    _ = io  # silence unused import lint if any
