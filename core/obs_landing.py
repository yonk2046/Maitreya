"""core/obs_landing.py — per-ticker O 態落地編排(P2-W3)

把「render-time 引擎判斷」搬進 pipeline、封印前落地(憲法不變量 #2:viewer 不算)。
本模組是 W3 per-ticker O 欄的**單一編排點**,ingest 的 `if obs_landing:` 掛點呼叫它。

落地欄(15 per-ticker O,design §1a):
  • obs_sm_*        (6) —— StateMachine:state/transition_risk/days_in_state/
                            state_entered/structure_unstable/risk_factors
  • obs_golden_*    (6) —— Golden:tier/conviction/action_group/gates_passed/
                            tier_caps/near_miss(含 missed_gate,**不落 tier**,#26)
  • obs_chip_grade  (1) —— Chip:{grade,total,items}(含 total 子值,#35)
  • obs_dist_consistency (1) —— Distribution:賣方一致性(唯一賣方證據源,#38;
                            不在賣方榜→null)
  • sync_streak     (1) —— temporal_enrich 系(在 ingest 迴圈落地,不經本模組)

呼叫順序(design §2c 偏序):breadth→regime→**sm→golden**→chip→dist→temperature。
本模組落 sm→golden→chip→dist:
  • sm 先於 golden,且 golden **改讀已落地 sm_states、不重跑 state_machine**
    (治 NOTES #30 雙真相病 — golden.run(window, sm_states=...))。
  • chip/dist 無跨引擎 O 依賴,可於 sm/golden 後插入。
market grain(breadth/regime/temperature)屬 W4,不在本模組。

C10 bootstrap(design §2d):sm 的 state/risk 等由 raw 歷史窗確定(純函式、
deterministic、與 render-time 一致);唯 **days_in_state/state_entered** 依 as-was
**已落地 obs_sm_state 序列**累計(core/history_view.days_in_state_from_landed),
1.9.0 首日之前無 landed 序列 → days_in_state=1、state_entered=今日,不回算 raw
偽造更早 entry(#48 look-ahead)。
"""
from __future__ import annotations

from typing import Any

from core import golden as _golden
from core import state_machine as _sm
from core import chip_score as _chip
from core import distribution as _dist
from core import history_view

# Golden gate keys, in G1..G5 order (mirrors golden._evaluate_gates).
_GATE_KEYS = [
    "G1_funnel_confirmation",
    "G2_state_confirmed_or_strengthening",
    "G3_sponsorship",
    "G4_risk_not_critical",
    "G5_net_positive",
]


def _gates_object(gates_passed: list[str]) -> dict[str, bool]:
    """{G1..G5: bool} from a golden entry's passed-gate list."""
    return {f"G{i + 1}": (_GATE_KEYS[i] in gates_passed) for i in range(len(_GATE_KEYS))}


def _sm_obs(ts, prior_snaps: list[dict], ticker: str, current_date: str) -> dict[str, Any]:
    """The six obs_sm_* fields for one ticker.

    state / transition_risk / structure_unstable / risk_factors come straight
    from run_all (pure raw-deterministic → matches render-time engine exactly).
    days_in_state / state_entered follow the C10 landed-series discipline via
    history_view (bootstrap first day → 1 / today).
    """
    state = ts.state
    days, entered = history_view.days_in_state_from_landed(
        prior_snaps, ticker, state, current_date)
    return {
        "obs_sm_state":              state,
        "obs_sm_transition_risk":    ts.transition_risk,
        "obs_sm_days_in_state":      days,
        "obs_sm_state_entered":      entered,
        "obs_sm_structure_unstable": bool(ts.structure_unstable),
        "obs_sm_risk_factors":       list(ts.risk_factors),
    }


def _golden_obs(ticker: str, gate_passing: dict, near_miss: dict, rec: dict) -> dict[str, Any]:
    """The six obs_golden_* fields for one ticker."""
    e = gate_passing.get(ticker)
    if e is not None:
        weak_sev = (rec.get("weakening") or {}).get("severity", "none")
        caps = ({"capped_to": e.tier, "reasons": list(e.tier_caps)}
                if e.tier_caps else None)
        return {
            "obs_golden_tier":         e.tier,
            "obs_golden_conviction":   round(e.conviction, 4),
            "obs_golden_action_group": _golden.action_group(e, weak_sev),
            "obs_golden_gates_passed": _gates_object(e.gates_passed),
            "obs_golden_tier_caps":    caps,
            "obs_golden_near_miss":    None,
        }
    nm = near_miss.get(ticker)
    if nm is not None:
        missed = [g for g in _GATE_KEYS if g not in nm.gates_passed]
        return {
            "obs_golden_tier":         None,   # #26: near_miss 不落 tier
            "obs_golden_conviction":   round(nm.conviction, 4),
            "obs_golden_action_group": None,
            "obs_golden_gates_passed": _gates_object(nm.gates_passed),
            "obs_golden_tier_caps":    None,
            "obs_golden_near_miss":    {"missed_gate": missed[0] if missed else None},
        }
    # Not in the golden layer at all (didn't pass gates, not a 1-gate near-miss).
    return {
        "obs_golden_tier":         None,
        "obs_golden_conviction":   None,
        "obs_golden_action_group": None,
        "obs_golden_gates_passed": {},
        "obs_golden_tier_caps":    None,
        "obs_golden_near_miss":    None,
    }


def _chip_obs(ts, rec: dict) -> dict[str, Any]:
    """obs_chip_grade {grade, total, max_total, items} for one ticker.

    streak / sponsorship read from the day's landed sm state (single source);
    the remaining inputs are I-state raw fields on the record.
    """
    cs = _chip.compute(
        streak=ts.streak if ts is not None else 0,
        sponsorship=ts.sponsorship_score if ts is not None else 0.0,
        fii_sync_count=rec.get("fii_sync_count"),
        main_force_buy=rec.get("main_force_buy"),
        market_volume=rec.get("market_volume"),
        main_force_cost=rec.get("main_force_cost"),
        current_price=rec.get("current_price"),
        top5_concentration=rec.get("top5_concentration"),
    )
    return {
        "grade":     cs.grade,
        "total":     cs.total,       # #35: total 子值(憲法 §4 off-by-one 來源)
        "max_total": cs.max_total,
        "items":     cs.items,
    }


def _dist_obs(entry) -> dict[str, Any] | None:
    """obs_dist_consistency for one ticker, or None.

    #38: obs_dist_consistency 是「唯一賣方證據源」——tickers 不在賣方榜(外資/主力
    賣超 raw 都沒上榜)→ **null**。有賣方訊號者才落一致性物件。
    """
    if entry is None:
        return None
    on_sell_board = (entry.foreign_status == "sell" or entry.main_status == "sell")
    if not on_sell_board:
        return None
    return {
        "consistency_grade":   entry.consistency_grade,
        "consistency_score":   entry.consistency_score,
        "consistency_reason":  entry.consistency_reason,
        "foreign_status":      entry.foreign_status,
        "main_status":         entry.main_status,
        "safety_margin":       entry.safety_margin,
        "safety_label":        entry.safety_label,
        "suggested_action":    entry.suggested_action,
        "flagged_for_removal": entry.flagged_for_removal,
    }


def compute_per_ticker_obs(
    window: list[dict],
    prior_snaps: list[dict],
    *,
    dist_raw: dict[str, list] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute the per-ticker O fields (obs_sm_*/obs_golden_*/obs_chip_grade/
    obs_dist_consistency) for the current (last) snapshot in `window`.

    Args:
        window: prior snapshots + the provisional current snapshot (built from
            today's records), oldest→newest. The engines read this as the 20-day
            history window.
        prior_snaps: the prior window only (window[:-1]) — used for the C10
            landed-series days_in_state counting.
        dist_raw: {"buy_list", "sell_list", "main_force_buy", "main_force_sell"}
            raw ranking lists for the day (from the adapter). None → distribution
            skipped (obs_dist_consistency stays null for every ticker).

    Returns: {ticker: {obs_field: value}} for every ticker in the current snapshot.
    """
    if not window:
        return {}
    current = window[-1]
    current_date = current.get("date", "")
    stock_map = {s["ticker"]: s for s in current.get("stocks", []) if s.get("ticker")}

    # ③ sm → ④ golden(golden 讀 ③ 的 sm_states,不重跑;#30)
    sm_states = _sm.run_all(window)
    golden_result = _golden.run(window, sm_states=sm_states)

    gate_passing: dict[str, Any] = {}
    for e in (golden_result.prime + golden_result.strong + golden_result.qualified):
        gate_passing[e.ticker] = e
    near_miss = {e.ticker: e for e in golden_result.near_miss}

    # ⑥ distribution(讀當日賣方 raw + 買方 raw ranking;純記憶體,無檔 I/O)
    dist_by: dict[str, Any] = {}
    if dist_raw is not None:
        dist_by = _dist.consistency_for_universe(
            stock_map,
            buy_list=dist_raw.get("buy_list", []) or [],
            sell_list=dist_raw.get("sell_list", []) or [],
            main_force_buy=dist_raw.get("main_force_buy", []) or [],
            main_force_sell=dist_raw.get("main_force_sell", []) or [],
        )["by_ticker"]

    out: dict[str, dict[str, Any]] = {}
    for ticker, rec in stock_map.items():
        ts = sm_states.get(ticker)
        obs: dict[str, Any] = {}
        if ts is not None:
            obs.update(_sm_obs(ts, prior_snaps, ticker, current_date))
        obs.update(_golden_obs(ticker, gate_passing, near_miss, rec))
        obs["obs_chip_grade"] = _chip_obs(ts, rec)
        obs["obs_dist_consistency"] = _dist_obs(dist_by.get(ticker))
        out[ticker] = obs
    return out
