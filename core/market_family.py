"""core/market_family.py — market-grain O 落地 (P2-W4, NOTES #40/#41/#43)

The **sole market-level producer** for the three landed date-grain O fields:

  • obs_market_breadth     — 真全市場漲跌家數母體 (market_pulse, twse_listed; #41)
  • obs_market_regime      — 市場體制 (regime_shift 收斂, 切點 engine_params; #40)
  • obs_market_temperature — 市場溫度 (讀當日已落地 obs_sm_transition_risk; #43)

裁定依據
--------
#40 市場級 SoR 收斂:market_state.py (888 行) 判死 (Phase 3 處決);regime_shift =
    唯一收斂點,遷移後市場級 O 搬出 market_context.py 成家。**本模組即那個家**:
    pipeline 落地的市場級真值一律由此產出。market_context.regime_shift 標 deprecated
    留原地不刪 (仍被 state_machine / confidence 於 render-time 消費;Phase 3 解散時
    一併處決),避免動 W3 已落地並 attested 的 obs_sm_*。

#41 母體修正 (P0 前置):breadth 恆 ≈1.0 的病根 = 用買超 top-N 榜當母體 (依構造
    恆真)。修法 = 讀 data/market_pulse/<date>.json 的 twse_listed 全市場漲跌家數。
    per-date 檔缺失 / errors 非空 / breadth 區塊解析失敗 → **誠實 null + reason**,
    **絕不 fallback 到榜母體**(fallback 回病態母體 = 復發 #41,把假訊號焊進 as-was)。

#43 temperature 移交收尾:elev_ratio 分子從已廢 confidence risk_level 改為讀**當日
    已落地 obs_sm_transition_risk** 聚合;dist_ratio 讀當日已落地 obs_sm_state 聚合
    (兩者皆源自 sm SoT,不再依賴 confidence 引擎);breadth 成分讀修正後 breadth 母體。

replay 安全:market_pulse per-date 檔為 P1-2 WORM 歸檔 (I 態, C7),replay 讀同一份
檔 → obs_market_* 逐 byte 重現。regime 的歷史 breadth_series 亦僅由 WORM pulse 建。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from core import engine_params as _cfg
from core.state_machine import S_CONFIRMED, S_STRENGTHENING, S_DISTRIBUTING

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
_MARKET_PULSE_DIR = _AI_STOCK / "data" / "market_pulse"


# ═══════════════════════════════════════════════════════════════════════════
# obs_market_breadth — 讀 market_pulse per-date 母體 (#41)
# ═══════════════════════════════════════════════════════════════════════════

def _pulse_path(date: str, base_dir: pathlib.Path | None) -> pathlib.Path:
    return (base_dir or _MARKET_PULSE_DIR) / f"{date}.json"


def load_pulse_breadth(date: str, base_dir: pathlib.Path | None = None) -> dict | None:
    """The parsed `breadth` block of data/market_pulse/<date>.json, or None.

    Returns None (never a fallback母體) when: file missing, JSON unreadable,
    `errors` non-empty, or the breadth block lacks advancers/decliners/total.
    """
    path = _pulse_path(date, base_dir)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if doc.get("errors"):
        return None
    b = doc.get("breadth")
    if not isinstance(b, dict):
        return None
    if b.get("advancers") is None or b.get("decliners") is None or not b.get("total"):
        return None
    return b


def compute_breadth(date: str, base_dir: pathlib.Path | None = None) -> dict[str, Any]:
    """obs_market_breadth for one date.

    breadth = advancers / total (twse_listed 母體). 缺料 → breadth=None + reason
    (誠實放棄,不用榜母體 fallback)。回傳物件永遠帶 advancers/decliners/total 供對照。
    """
    b = load_pulse_breadth(date, base_dir)
    if b is None:
        return {
            "breadth":    None,
            "advancers":  None,
            "decliners":  None,
            "unchanged":  None,
            "total":      None,
            "universe":   None,
            "source":     "market_pulse",
            "reason":     "market_pulse_missing_or_error",
        }
    advancers = int(b["advancers"])
    decliners = int(b["decliners"])
    total = int(b["total"])
    breadth = round(advancers / total, 4) if total else None
    return {
        "breadth":    breadth,
        "advancers":  advancers,
        "decliners":  decliners,
        "unchanged":  b.get("unchanged"),
        "total":      total,
        "universe":   b.get("universe", "twse_listed_stocks"),
        "source":     b.get("source", "market_pulse"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# obs_market_regime — regime_shift 收斂,breadth 母體修正,切點 engine_params (#40)
# ═══════════════════════════════════════════════════════════════════════════

def _empty_regime() -> dict[str, Any]:
    return dict(
        dates=[], breadth_series=[], avg_chg_series=[],
        fii_active_series=[], vol_series=[], breadth_trend="flat",
        latest_breadth=None, latest_avg_chg=0.0, latest_vol_index=1.0,
        regime_label_zh="無資料", regime_label_en="No Data",
        regime_color="#6B8EAA", transition_detected=False, transition_note="",
        breadth_universe=None,
    )


def regime(
    snapshots: list[dict[str, Any]],
    base_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Market-regime classification across the window.

    Moved from market_context.regime_shift (#40 收斂),with the **breadth
    dimension re-based off market_pulse母體** instead of the buy-super榜
    (sum(mf>0)/len — 恆 ≈1.0 病, #41). avg_chg / fii_active / vol_index keep
    their universe-relative definitions (used only for internal classification;
    obs_market_avg_chg 不落, #40 C9). Regime切點 read from engine_params (MC_*).

    breadth_series is built only from dates whose WORM market_pulse exists
    (deterministic + replay-safe); dates lacking pulse are omitted from the
    breadth trend rather than reintroducing the榜母體 (honest gap, #41/C10).
    """
    if not snapshots:
        return _empty_regime()

    dates, avg_chg_s, fii_s, vol_s = [], [], [], []
    breadth_dates, breadth_s = [], []
    base_vol: float | None = None
    latest_universe: str | None = None

    for snap in snapshots:
        stocks = snap.get("stocks", [])
        if not stocks:
            continue
        d = snap.get("date", "?")
        dates.append(d)

        chg_vals = [s.get("change_pct") for s in stocks if s.get("change_pct") is not None]
        fii_vals = [s.get("fii_net_buy") for s in stocks if s.get("fii_net_buy") is not None]
        vol_vals = [s.get("volume") for s in stocks if s.get("volume") is not None]

        avg_chg = sum(chg_vals) / len(chg_vals) if chg_vals else 0.0
        fii_act = sum(1 for v in fii_vals if v != 0) / max(len(fii_vals), 1) if fii_vals else 0.0
        total_vol = sum(vol_vals)

        if base_vol is None:
            base_vol = total_vol if total_vol > 0 else 1
        vol_idx = total_vol / base_vol

        avg_chg_s.append(round(avg_chg, 3))
        fii_s.append(round(fii_act, 3))
        vol_s.append(round(vol_idx, 3))

        # breadth 母體修正:讀 market_pulse (twse_listed), 缺 pulse → 不入 series
        bobj = compute_breadth(d, base_dir)
        if bobj["breadth"] is not None:
            breadth_dates.append(d)
            breadth_s.append(bobj["breadth"])
            latest_universe = bobj["universe"]

    if not dates:
        return _empty_regime()

    latest_chg = avg_chg_s[-1]
    latest_b: float | None = breadth_s[-1] if breadth_s else None

    # Breadth trend over last points (切點 engine_params;僅在有 ≥2 pulse 點時判)
    breadth_trend = "flat"
    if len(breadth_s) >= 2:
        delta = breadth_s[-1] - breadth_s[-2]
        if len(breadth_s) >= 3:
            delta2 = breadth_s[-2] - breadth_s[-3]
            if delta > _cfg.MC_BREADTH_TREND_FAST and delta2 >= 0:
                breadth_trend = "rising_fast"
            elif delta > _cfg.MC_BREADTH_TREND_SLOW:
                breadth_trend = "rising"
            elif delta < -_cfg.MC_BREADTH_TREND_FAST:
                breadth_trend = "falling_fast"
            elif delta < -_cfg.MC_BREADTH_TREND_SLOW:
                breadth_trend = "falling"
        else:
            breadth_trend = ("rising" if delta > _cfg.MC_BREADTH_TREND_SLOW
                             else "falling" if delta < -_cfg.MC_BREADTH_TREND_SLOW
                             else "flat")

    # Regime classification (切點 engine_params). breadth 缺料 → 只依 avg_chg 給
    # 中性/偏弱,不假造 breadth 維度。
    if latest_b is None:
        if latest_chg < 0:
            regime_zh, regime_en, regime_color = "偏弱整理", "Mild Risk-Off", "#C47A5A"
        else:
            regime_zh, regime_en, regime_color = "中性整理", "Neutral / Consolidating", "#6B8EAA"
    elif latest_b >= _cfg.MC_REGIME_OFFENSIVE_BREADTH and latest_chg > _cfg.MC_REGIME_OFFENSIVE_CHG:
        regime_zh, regime_en, regime_color = "強勢進攻", "Risk-On / Offensive", "#52B788"
    elif latest_b >= _cfg.MC_REGIME_MILD_RISKON_BREADTH and latest_chg > _cfg.MC_REGIME_MILD_RISKON_CHG:
        regime_zh, regime_en, regime_color = "溫和偏多", "Mild Risk-On", "#7EB8D4"
    elif latest_b < _cfg.MC_REGIME_RETREAT_BREADTH and latest_chg < _cfg.MC_REGIME_RETREAT_CHG:
        regime_zh, regime_en, regime_color = "全面撤退", "Risk-Off / Retreat", "#E05C7A"
    elif latest_b < _cfg.MC_REGIME_WAITING_BREADTH:
        regime_zh, regime_en, regime_color = "資金觀望", "Capital Waiting", "#D4A84B"
    elif latest_chg < 0:
        regime_zh, regime_en, regime_color = "偏弱整理", "Mild Risk-Off", "#C47A5A"
    else:
        regime_zh, regime_en, regime_color = "中性整理", "Neutral / Consolidating", "#6B8EAA"

    # Transition detection (切點 engine_params)
    transition_detected, transition_note = False, ""
    if len(breadth_s) >= 2:
        b_delta = breadth_s[-1] - breadth_s[-2]
        c_delta = avg_chg_s[-1] - avg_chg_s[-2]
        if abs(b_delta) >= _cfg.MC_TRANSITION_BREADTH_DELTA or abs(c_delta) >= _cfg.MC_TRANSITION_CHG_DELTA:
            transition_detected = True
            transition_note = ("市場突然轉強 — 可能 Risk-Off→Risk-On 切換" if b_delta > 0
                               else "市場突然轉弱 — 資金快速撤出訊號")

    return {
        "dates":               dates,
        "breadth_dates":       breadth_dates,
        "breadth_series":      breadth_s,
        "avg_chg_series":      avg_chg_s,
        "fii_active_series":   fii_s,
        "vol_series":          vol_s,
        "breadth_trend":       breadth_trend,
        "latest_breadth":      latest_b,
        "latest_avg_chg":      latest_chg,
        "latest_vol_index":    vol_s[-1] if vol_s else 1.0,
        "regime_label_zh":     regime_zh,
        "regime_label_en":     regime_en,
        "regime_color":        regime_color,
        "transition_detected": transition_detected,
        "transition_note":     transition_note,
        "breadth_universe":    latest_universe,
    }


# ═══════════════════════════════════════════════════════════════════════════
# obs_market_temperature — 讀當日已落地 obs_sm_transition_risk + 修正 breadth (#43)
# ═══════════════════════════════════════════════════════════════════════════

def compute_temperature(
    stocks: list[dict[str, Any]],
    breadth_obj: dict[str, Any],
) -> dict[str, Any]:
    """obs_market_temperature from the day's **landed** per-ticker sm fields.

    #43 rewrite (no confidence dependency):
      • elev_ratio  = share of tickers whose landed obs_sm_transition_risk is
                      elevated/critical (was confidence risk_level — 已廢).
      • dist_ratio  = distributing share among active states, read from landed
                      obs_sm_state (confirmed / strengthening / distributing).
      • breadth_risk= 1 − corrected breadth母體 (obs_market_breadth). breadth 缺料
                      → 中性 0.5 (誠實,不假造),temperature 仍由 sm 成分 (70%) 支撐。

    TEMP_* weights & TEMP_LEVELS sourced from engine_params (config-frozen, C11).
    """
    risks = [s.get("obs_sm_transition_risk") for s in stocks
             if s.get("obs_sm_transition_risk") is not None]
    states = [s.get("obs_sm_state") for s in stocks
              if s.get("obs_sm_state") is not None]
    n = len(risks)

    if n == 0:
        return {
            "temperature":         0.0,
            "temperature_level":   "cool",
            "temperature_zh":      "冷靜",
            "temperature_color":   "#52B788",
            "elevated_risk_ratio": 0.0,
            "distributing_ratio":  0.0,
            "breadth_signal":      breadth_obj.get("breadth"),
            "breadth_risk":        0.5,
            "total_tracked":       0,
            "confirmed_count":     0,
            "strengthening_count": 0,
            "distributing_count":  0,
            "risk_source":         "obs_sm_transition_risk",
        }

    elevated_n = sum(1 for r in risks if r in ("elevated", "critical"))
    elev_ratio = elevated_n / n

    conf_n = sum(1 for s in states if s == S_CONFIRMED)
    str_n = sum(1 for s in states if s == S_STRENGTHENING)
    dist_n = sum(1 for s in states if s == S_DISTRIBUTING)
    denom = conf_n + str_n + dist_n
    dist_ratio = dist_n / denom if denom > 0 else 0.0

    breadth_val = breadth_obj.get("breadth")
    breadth_risk = (1.0 - breadth_val) if breadth_val is not None else 0.5

    temperature = min(1.0, (
        _cfg.TEMP_W_RISK_RATIO * elev_ratio
        + _cfg.TEMP_W_DISTRIB * dist_ratio
        + _cfg.TEMP_W_BREADTH * breadth_risk
    ))

    t_level, t_zh, t_color = "cool", "冷靜", "#52B788"
    for threshold, level, zh, color in _cfg.TEMP_LEVELS:
        if temperature >= threshold:
            t_level, t_zh, t_color = level, zh, color
            break

    return {
        "temperature":         round(temperature, 4),
        "temperature_level":   t_level,
        "temperature_zh":      t_zh,
        "temperature_color":   t_color,
        "elevated_risk_ratio": round(elev_ratio, 4),
        "distributing_ratio":  round(dist_ratio, 4),
        "breadth_signal":      breadth_val,
        "breadth_risk":        round(breadth_risk, 4),
        "total_tracked":       n,
        "confirmed_count":     conf_n,
        "strengthening_count": str_n,
        "distributing_count":  dist_n,
        "risk_source":         "obs_sm_transition_risk",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrator — the three market-grain fields for one snapshot day
# ═══════════════════════════════════════════════════════════════════════════

def compute_market_obs(
    date: str,
    window: list[dict[str, Any]],
    stocks: list[dict[str, Any]],
    base_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Produce {obs_market_breadth, obs_market_regime, obs_market_temperature}
    plus any honest data-gap error strings for the snapshot's errors log.

    Order (design §2c ⑦):breadth → regime → temperature. temperature reads the
    already-landed obs_sm_* on `stocks` (per-ticker O landed earlier in ingest).
    """
    errors: list[str] = []

    breadth = compute_breadth(date, base_dir)
    if breadth["breadth"] is None:
        errors.append(f"obs_market_breadth null: {breadth.get('reason')} ({date})")

    reg = regime(window, base_dir)
    temp = compute_temperature(stocks, breadth)

    return {
        "obs_market_breadth":      breadth,
        "obs_market_regime":       reg,
        "obs_market_temperature":  temp,
        "errors":                  errors,
    }
