"""守門員:feature_flags.engine_correction_v1(AUDIT-golden-list-20260922 G1/G3/G9)。

- 旗標關閉 = 舊行為逐位元不變(全量保證在 tools/verify_all_replay.py;此處測介面預設值)。
- 旗標開啟:
  G3 缺席不再透明 —— 掉出主力榜的那天中斷連買;
  G1 轉弱用「前序 + 今天」判斷 —— W3「主力消失」不再亮在回榜當天,而是亮在真的消失那天;
  G9 狀態機 CONFIRMED 的廣度閘改讀全市場 market_pulse(缺值 = 不放行)。
"""
from __future__ import annotations

import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import golden, state_machine as smod  # noqa: E402
from core.market_context import (  # noqa: E402
    accumulation_velocity, ticker_records, weakening_profile,
)


def _snap(date, *tickers, mfb=100):
    return {"date": date, "stocks": [{"ticker": t, "main_force_buy": mfb} for t in tickers]}


# 2330 在榜 3 天 → 缺席 1 天 → 回榜
SEQ = [_snap("2026-09-01", "2330"), _snap("2026-09-02", "2330"), _snap("2026-09-03", "2330"),
       _snap("2026-09-04"), _snap("2026-09-07", "2330")]


def test_ticker_records_legacy_skips_absent_days():
    assert [r["date"] for r in ticker_records("2330", SEQ)] == [
        "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-07"]


def test_absence_breaks_streak_under_correction():
    legacy = accumulation_velocity("2330", ticker_records("2330", SEQ))
    fixed = accumulation_velocity("2330", ticker_records("2330", SEQ, absent_as_zero=True))
    assert legacy["streak"] == 4          # 舊:缺席那天被跳過,「連買 4 天」
    assert fixed["streak"] == 1           # 新:9/04 不在榜 → 中斷,只算 9/07


def _codes(w):
    return {f["code"] for f in w["flags"]}


def test_w3_legacy_fires_on_the_day_the_ticker_comes_back():
    """舊 ingest 只給前序窗口(最後一天 = 昨天)→ 回榜當天被標「主力消失」。"""
    assert "W3" in _codes(weakening_profile("2330", SEQ[:-1]))


def test_w3_corrected_not_on_return_day_but_on_vanish_day():
    assert "W3" not in _codes(weakening_profile("2330", SEQ, correction=True))       # 回榜當天
    assert "W3" in _codes(weakening_profile("2330", SEQ[:-1], correction=True))      # 9/04 消失當天


def test_w3_corrected_requires_a_truly_consecutive_streak():
    gappy = [_snap("2026-09-01", "2330"), _snap("2026-09-02"), _snap("2026-09-03", "2330"),
             _snap("2026-09-04"), _snap("2026-09-07", "2330"), _snap("2026-09-08")]
    assert "W3" in _codes(weakening_profile("2330", gappy))                          # 舊:跳著算也算「連買 3 日」
    assert "W3" not in _codes(weakening_profile("2330", gappy, correction=True))     # 新:從未連續 3 日


# ── 真實快照:掉榜股不得再掛黃金(G4) ──────────────────────────────────────────

def _window(date, days=20):
    import datetime as dt
    idx = json.loads((_ROOT / "reports" / "index.json").read_text())["snapshots"]
    ds = sorted(d for d, e in idx.items() if "example" not in d and "example" not in e["current"])
    d0 = dt.date.fromisoformat(date)
    pick = [d for d in ds if 0 <= (d0 - dt.date.fromisoformat(d)).days <= days]
    return [json.loads((_ROOT / "reports" / idx[d]["current"]).read_text()) for d in pick]


def _golden_tickers(win, correction):
    g = golden.run(win, sm_states=smod.run_all(win, correction=correction), correction=correction)
    return {e.ticker for e in g.prime + g.strong + g.qualified}


def test_real_2026_08_27_absent_tickers_leave_golden_under_correction():
    win = _window("2026-08-27")
    present = {s["ticker"] for s in win[-1]["stocks"]}
    legacy = _golden_tickers(win, False)
    assert legacy - present, "前提:舊算法在 8/27 把當天不在榜的股票列進黃金(AUDIT G4)"
    assert not (_golden_tickers(win, True) - present)


def test_breadth_gate_reads_market_pulse_and_fails_closed(monkeypatch):
    import core.market_family as mf
    win = _window("2026-08-27")
    legacy_states = {t: s.state for t, s in smod.run_all(win).items()}
    assert smod.S_CONFIRMED in legacy_states.values(), "前提:舊廣度閘(≈1.0)放行 CONFIRMED"
    monkeypatch.setattr(mf, "compute_breadth", lambda d, base_dir=None: {"breadth": 0.30})
    weak = {t: s.state for t, s in smod.run_all(win, correction=True).items()}
    assert smod.S_CONFIRMED not in weak.values()
    monkeypatch.setattr(mf, "compute_breadth", lambda d, base_dir=None: {"breadth": None})
    missing = {t: s.state for t, s in smod.run_all(win, correction=True).items()}
    assert smod.S_CONFIRMED not in missing.values()       # 缺廣度 → 不放行


def test_flag_defaults_to_legacy_everywhere():
    import inspect
    from core import funnel, obs_landing, market_context
    for fn in (golden.run, smod.run_all, smod.compute, funnel.run, obs_landing.compute_per_ticker_obs,
               market_context.weakening_profile, market_context.temporal_enrich):
        assert inspect.signature(fn).parameters["correction"].default is False, fn.__qualname__


def test_example_config_ships_flag_off_until_go_live():
    import yaml
    cfg = yaml.safe_load((_ROOT / "config" / "scd.example.yaml").read_text(encoding="utf-8"))
    assert (cfg.get("feature_flags") or {}).get("engine_correction_v1") is False, (
        "上線前旗標必須為 false;2026-10-02 收盤後才改 true(EXEC-PLAN-engine-correction-20260922)。"
        "上線時一併把本測試改為 True。")


def test_one_day_absence_is_not_a_hard_structural_failure():
    """審查 60ebcf7 #3:缺席佔位(mfb 0)曾觸發「連買崩塌→FAILED」(當日定案硬狀態),
    1 日輪動就被判結構失敗且回榜後仍卡住。缺席改交給 W3/EXITED 判斷。"""
    seq = [_snap("2026-09-01", "2330"), _snap("2026-09-02", "2330"), _snap("2026-09-03", "2330"),
           _snap("2026-09-04")]
    st = smod.run_all(seq, correction=True)["2330"].state
    assert st != smod.S_FAILED
    back = seq + [_snap("2026-09-07", "2330")]
    assert smod.run_all(back, correction=True)["2330"].state != smod.S_FAILED


def test_real_data_failed_while_buying_not_inflated():
    """審查實測:7/13–9/22 在榜且主力買超卻顯示 FAILED 的股票日,舊 27 → 錯誤版 220。修正後不得暴增。"""
    import datetime as dt
    idx = json.loads((_ROOT / "reports" / "index.json").read_text())["snapshots"]
    ds = sorted(d for d, e in idx.items() if "example" not in d and "example" not in e["current"])
    snaps = {d: json.loads((_ROOT / "reports" / idx[d]["current"]).read_text()) for d in ds}
    bad = {False: 0, True: 0}
    for d in ds:
        if not ("2026-08-01" <= d <= "2026-09-22"):
            continue
        d0 = dt.date.fromisoformat(d)
        win = [snaps[x] for x in ds if 0 <= (d0 - dt.date.fromisoformat(x)).days <= 20]
        today = {s["ticker"]: s for s in snaps[d]["stocks"]}
        for corr in (False, True):
            for t, ts in smod.run_all(win, correction=corr).items():
                if t in today and (today[t].get("main_force_buy") or 0) > 0 and ts.state == smod.S_FAILED:
                    bad[corr] += 1
    assert bad[True] <= bad[False] * 1.5 + 5, bad


def test_strategy_tags_accept_flag():
    import inspect
    from core import strategies
    assert inspect.signature(strategies.strategy_tags_for_date).parameters["correction"].default is False
    assert inspect.signature(strategies.would_enter).parameters["correction"].default is False
