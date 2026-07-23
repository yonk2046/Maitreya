"""core/paper_trading.py — deterministic paper-trading / backtest engine (P3b).

Pure function: (snapshot sequence, StrategyConfig) → trade records + summary.
No I/O, no randomness, no network. The CLI wrapper (tools/run_backtest.py)
handles loading/writing.

Governance + spec discipline:
  • Rules live in core/strategies.py (config); this engine只執行.
  • No look-ahead: decisions for day D use ONLY snapshots[:D+1]; the fill
    happens on D+1. We never read a future snapshot to decide a past day.
  • Chip-defined exits (轉弱/外資反向); trailing stop is the one price exit
    allowed for the momentum strategy (spec §67).

v1 limitations (surfaced in the result + report):
  • Settlement uses next-day current_price (close) as an open-price proxy —
    snapshots carry no open price (spec §99). Documented, not silent.
  • Fixed 1-unit position; 加碼/減碼 partial sizing deferred to v2.
  • Momentum strategy needs fii_net_buy (from 2026-06-12) and weakening
    (from schema 1.6.0 / 2026-06-15); effective window starts there.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from core.engine_params import (
    BACKTEST_ADD_MIN_PRICE_MULT,
    BACKTEST_COOLDOWN_DAYS,
    BACKTEST_FEE_MIN,
    BACKTEST_FEE_RATE,
    BACKTEST_INITIAL_CAPITAL,
    BACKTEST_POSITION_SIZE,
    BACKTEST_TAX_RATE,
)
from core.market_context import temporal_enrich
from core.strategies import StrategyConfig, would_enter


# ── Output structures ──────────────────────────────────────────────────────

@dataclass
class Trade:
    ticker: str
    name: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    exit_reason: str          # trailing_stop | weakening | fii_reversal | tp1 | tp2 | atr_stop | end_of_data
    holding_days: int
    units: float = 1.0        # v2 partial sizing: this leg's size (1.0 for v1 full)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["return_pct"] = round(self.return_pct, 4)
        d["entry_price"] = round(self.entry_price, 2)
        d["exit_price"] = round(self.exit_price, 2)
        d["units"] = round(self.units, 2)
        return d


@dataclass
class BacktestResult:
    strategy: str
    date_range: tuple[str, str]
    trades: list[Trade] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "date_range": list(self.date_range),
            "trade_count": len(self.trades),
            "summary": self.summary,
            "limitations": self.limitations,
            "trades": [t.as_dict() for t in self.trades],
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

# 3.4 報告揭露口徑(單一字串常數,避免各處複製漂移)。
_DISCLOSURE_NOTE = (
    "頂層 avg_return/win_rate/median 含全部交易(含 end_of_data 未實現部位);"
    "realized/unrealized 已分離(3.4)——未實現不得混入已實現統計。"
    "信賴區間一律以 independent_tickers(獨立標的數)計,非交易筆數。"
)


def _rec_for(snap: dict, ticker: str) -> dict | None:
    for s in snap.get("stocks", []):
        if s.get("ticker") == ticker:
            return s
    return None


def _fill_price(snap: dict, ticker: str) -> float | None:
    """Execution price on a snapshot: next-day open if present, else close."""
    rec = _rec_for(snap, ticker)
    if rec is None:
        return None
    return rec.get("open") or rec.get("current_price")


def _weakening_sev(rec: dict) -> str:
    return ((rec or {}).get("weakening") or {}).get("severity", "none")


def _in_cooldown(cooldown: dict[str, int], ticker: str, entry_fill_i: int) -> bool:
    """3.3 冷卻期:出場後 N 個交易日內同標的禁再進場(純成本消耗的洗單防護)。

    cooldown[ticker] = 該標的上次「完全出場」的成交日索引(fill index)。
    prospective 進場成交日索引 = entry_fill_i。gap = entry_fill_i − last_exit_i。
    gap < BACKTEST_COOLDOWN_DAYS → 禁(含同日 gap==0)。COOLDOWN_DAYS==0 → 恆不禁
    (掃描對照組)。參數見 core/engine_params.py(BACKTEST_*,研究層,不入 config_hash)。
    """
    last_exit_i = cooldown.get(ticker)
    if last_exit_i is None:
        return False
    return (entry_fill_i - last_exit_i) < BACKTEST_COOLDOWN_DAYS


# ── Engine ────────────────────────────────────────────────────────────────────

def run_backtest(snapshots: list[dict], strategy: StrategyConfig) -> BacktestResult:
    """Run one strategy over a chronological snapshot sequence.

    Decisions on day i use snapshots[:i+1]; fills happen on day i+1.
    """
    snaps = sorted(snapshots, key=lambda s: s.get("date", ""))
    n = len(snaps)
    dates = [s.get("date", "") for s in snaps]
    result = BacktestResult(
        strategy=strategy.name,
        date_range=(dates[0] if dates else "", dates[-1] if dates else ""),
        limitations=[
            "settlement uses next-day close as open-price proxy (snapshots carry no open)",
            "fixed 1-unit position; 加碼/減碼 partial sizing deferred",
            "momentum needs fii (from 2026-06-12) + weakening (from 2026-06-15)",
            "資金曲線(2.2):P&L 於出場日一次性實現,非逐日 mark-to-market"
            "(快照無未平倉逐日估值);成本模型見 summary.cost_model(R2:參數在"
            "core/engine_params.py BACKTEST_*,不入 config_hash)",
        ],
    )
    if n < 2 or not strategy.enabled:
        result.summary = _summarize([], strategy)
        if not strategy.enabled:
            result.limitations.append(f"strategy '{strategy.name}' is disabled")
        return result

    if strategy.partial_sizing:
        return _run_backtest_v2(snaps, dates, strategy, result)

    chip = strategy.kind == "chip_anchored"
    if chip:
        from core import golden as _golden   # lazy: heavy funnel/state engine only when needed
        result.limitations.append(
            "chip-anchored v1: full position (TP1 partial / 加碼 / ATR structural stop deferred); "
            "golden membership computed on-the-fly via golden.run over each slice")

    open_pos: dict[str, dict] = {}   # ticker -> {entry_date, entry_price, peak, fii_neg_run, mfb_neg_run}
    cooldown: dict[str, int] = {}    # 3.3: ticker -> 上次完全出場的 fill index(冷卻期防洗單)

    # iterate decision days i = 0..n-2 (fill on i+1)
    for i in range(n - 1):
        decide, fill = snaps[i], snaps[i + 1]

        # ---- manage open positions (decide on i, execute on i+1) ----
        for ticker in list(open_pos.keys()):
            pos = open_pos[ticker]
            rec = _rec_for(decide, ticker)
            price = rec.get("current_price") if rec else None
            if price is None:
                continue
            pos["peak"] = max(pos["peak"], price)

            fii = (rec.get("fii_net_buy") or 0) if rec else 0
            pos["fii_neg_run"] = pos["fii_neg_run"] + 1 if fii < 0 else 0
            mfb = (rec.get("main_force_buy") or 0) if rec else 0
            pos["mfb_neg_run"] = pos["mfb_neg_run"] + 1 if mfb < 0 else 0

            reason = None
            if _weakening_sev(rec) in strategy.exit_on_weakening:
                reason = "weakening"               # 轉弱紅/橙 — chip-defined exit (both)
            elif chip:
                # 主力連 2 日淨賣/翻負 → 硬止損 + TP2 spirit (chip-defined, no price trailing)
                if pos["mfb_neg_run"] >= 2:
                    reason = "main_force_sell"
            else:
                if pos["fii_neg_run"] >= strategy.fii_reversal_days:
                    reason = "fii_reversal"
                elif price <= pos["peak"] * (1 - strategy.trailing_stop_pct):
                    reason = "trailing_stop"

            if reason:
                fp = _fill_price(fill, ticker)
                if fp is None:
                    continue
                result.trades.append(_close(pos, ticker, decide, fill, fp, reason, dates, i))
                del open_pos[ticker]
                cooldown[ticker] = i + 1        # 3.3: 出場成交日 → 起算冷卻期

        # ---- new entries (decide on i, execute on i+1) ----
        # 進場判斷共用 core.strategies.would_enter — 回測與 UI 標示的單一事實來源
        # (治理紅線 5)。切片 snaps[:i+1] 防前視;chip 型共用當日 golden.run(gres)。
        gres = None
        if chip:
            gres = _golden.run(snaps[:i + 1])           # golden list as of day i (no look-ahead)
        slice_upto = snaps[:i + 1]

        for rec in decide.get("stocks", []):
            ticker = rec.get("ticker")
            if not ticker or ticker in open_pos:
                continue
            if _in_cooldown(cooldown, ticker, i + 1):   # 3.3: 冷卻期內禁再進場
                continue
            ok, _reasons = would_enter(ticker, slice_upto, strategy, golden_result=gres)
            if not ok:
                continue
            fp = _fill_price(fill, ticker)
            if fp is None:
                continue
            open_pos[ticker] = {
                "entry_date": dates[i + 1], "entry_price": fp,
                "peak": fp, "fii_neg_run": 0, "mfb_neg_run": 0,
                "name": rec.get("name", ""), "entry_i": i + 1,
            }

    # ---- settle anything still open at the last snapshot ----
    last = snaps[-1]
    for ticker, pos in open_pos.items():
        fp = _fill_price(last, ticker)
        if fp is None:
            continue
        ret = (fp - pos["entry_price"]) / pos["entry_price"] if pos["entry_price"] else 0.0
        result.trades.append(Trade(
            ticker=ticker, name=pos["name"],
            entry_date=pos["entry_date"], entry_price=pos["entry_price"],
            exit_date=dates[-1], exit_price=fp, return_pct=ret,
            exit_reason="end_of_data", holding_days=(n - 1) - pos["entry_i"],
        ))

    result.summary = _summarize(result.trades, strategy)
    return result


def _close(pos, ticker, decide, fill, fill_price, reason, dates, i) -> Trade:
    ret = (fill_price - pos["entry_price"]) / pos["entry_price"] if pos["entry_price"] else 0.0
    return Trade(
        ticker=ticker, name=pos["name"],
        entry_date=pos["entry_date"], entry_price=pos["entry_price"],
        exit_date=dates[i + 1], exit_price=fill_price, return_pct=ret,
        exit_reason=reason, holding_days=(i + 1) - pos["entry_i"],
    )


def _net_return_pct(gross_return: float, units: float) -> float:
    """毛報酬 → 淨報酬(扣雙邊手續費 + 賣出證交稅)。

    2.1 成本模型(R2:參數見 core/engine_params.py BACKTEST_*,研究層,不入
    config_hash)。部位金額 = BACKTEST_POSITION_SIZE × units(units=1.0 為一個
    完整部位;v2 加碼/減碼/TP1 的分批 leg 用各自的 units 分數)。
    """
    entry_notional = BACKTEST_POSITION_SIZE * units
    if entry_notional <= 0:
        return gross_return
    exit_notional = entry_notional * (1 + gross_return)
    buy_fee = max(BACKTEST_FEE_RATE * entry_notional, BACKTEST_FEE_MIN)
    sell_fee = max(BACKTEST_FEE_RATE * exit_notional, BACKTEST_FEE_MIN)
    sell_tax = BACKTEST_TAX_RATE * exit_notional
    return gross_return - (buy_fee + sell_fee + sell_tax) / entry_notional


def _cost_model_dict() -> dict[str, float]:
    return {
        "fee_rate": BACKTEST_FEE_RATE,
        "fee_min": BACKTEST_FEE_MIN,
        "tax_rate": BACKTEST_TAX_RATE,
        "position_size": BACKTEST_POSITION_SIZE,
        "initial_capital": BACKTEST_INITIAL_CAPITAL,
    }


def _sharpe(rets: list[float], mean: float) -> float | None:
    # Per-trade Sharpe = mean / sample-stdev of trade returns (risk-free ≈ 0
    # per trade). NOT annualised. Small-sample → noisy; treat as directional.
    n = len(rets)
    if n < 2:
        return None
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    sd = var ** 0.5
    return round(mean / sd, 2) if sd > 0 else None


def _equity_curve(trades: list[Trade]) -> tuple[list[dict], float]:
    """資金曲線(2.2):BACKTEST_INITIAL_CAPITAL 起始,每筆交易以
    BACKTEST_POSITION_SIZE × units 為部位金額;淨(扣成本)損益在出場日實現。

    真正峰谷回撤(max_drawdown)——與 worst_single_trade(單筆報酬)分開計算,
    修正舊版「max_drawdown 恰等於某單筆報酬」的語意錯誤(前次分析發現)。

    限制:P&L 於出場日一次性實現,非逐日 mark-to-market(快照無未平倉逐日估值)。
    """
    ordered = sorted(trades, key=lambda t: (t.exit_date, t.entry_date))
    equity = BACKTEST_INITIAL_CAPITAL
    peak = equity
    mdd = 0.0
    curve = [{"date": None, "equity": round(equity, 2), "drawdown": 0.0}]
    for t in ordered:
        net = _net_return_pct(t.return_pct, t.units)
        pnl = BACKTEST_POSITION_SIZE * t.units * net
        equity += pnl
        peak = max(peak, equity)
        dd = (equity - peak) / peak if peak else 0.0
        mdd = min(mdd, dd)
        curve.append({"date": t.exit_date, "equity": round(equity, 2), "drawdown": round(dd, 4)})
    return curve, round(mdd, 4)


def _return_stats(trades: list[Trade]) -> dict[str, Any]:
    """毛+淨的一組報酬統計(3.4 已實現/未實現分離用的可複用區塊)。

    空集合回傳全 None 骨架。net 用 _net_return_pct(逐筆扣成本)。
    """
    if not trades:
        return {"trades": 0, "win_rate": None, "avg_return": None, "median_return": None,
                "net": {"win_rate": None, "avg_return": None, "median_return": None}}
    rets = sorted(t.return_pct for t in trades)
    n = len(rets)
    wins = sum(1 for r in rets if r > 0)
    mean = sum(rets) / n
    median = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    net_rets = sorted(_net_return_pct(t.return_pct, t.units) for t in trades)
    n_wins = sum(1 for r in net_rets if r > 0)
    n_mean = sum(net_rets) / n
    n_median = net_rets[n // 2] if n % 2 else (net_rets[n // 2 - 1] + net_rets[n // 2]) / 2
    return {
        "trades": n,
        "win_rate": round(wins / n, 4),
        "avg_return": round(mean, 4),
        "median_return": round(median, 4),
        "net": {"win_rate": round(n_wins / n, 4),
                "avg_return": round(n_mean, 4),
                "median_return": round(n_median, 4)},
    }


def _summarize(trades: list[Trade], strategy: StrategyConfig) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0, "win_rate": None, "avg_return": None,
            "median_return": None, "sharpe_per_trade": None,
            "avg_holding_days": None, "max_drawdown": None,
            "worst_single_trade": None,
            "net": {"win_rate": None, "avg_return": None,
                    "median_return": None, "sharpe_per_trade": None},
            "realized": _return_stats([]),
            "unrealized": _return_stats([]),
            "independent_tickers": 0,
            "disclosure": _DISCLOSURE_NOTE,
            "cost_model": _cost_model_dict(),
            "equity_curve": [],
        }
    rets = sorted(t.return_pct for t in trades)
    wins = sum(1 for r in rets if r > 0)
    n = len(rets)
    mean = sum(rets) / n
    median = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    sharpe = _sharpe(rets, mean)
    worst_single_trade = rets[0]   # 獨立欄位(2.2):最小單筆報酬,與 max_drawdown 分開

    # 2.1 淨報酬(扣成本)統計 — 與毛報酬並列,不取代
    net_rets = sorted(_net_return_pct(t.return_pct, t.units) for t in trades)
    n_wins = sum(1 for r in net_rets if r > 0)
    n_mean = sum(net_rets) / n
    n_median = net_rets[n // 2] if n % 2 else (net_rets[n // 2 - 1] + net_rets[n // 2]) / 2
    n_sharpe = _sharpe(net_rets, n_mean)

    equity_curve, mdd = _equity_curve(trades)

    return {
        "trades": n,
        "win_rate": round(wins / n, 4),
        "avg_return": round(mean, 4),
        "median_return": round(median, 4),
        "sharpe_per_trade": sharpe,
        "avg_holding_days": round(sum(t.holding_days for t in trades) / n, 2),
        "max_drawdown": mdd,                          # 2.2:真實資金曲線峰谷回撤
        "worst_single_trade": round(worst_single_trade, 4),
        "exit_reasons": _count_reasons(trades),
        "net": {
            "win_rate": round(n_wins / n, 4),
            "avg_return": round(n_mean, 4),
            "median_return": round(n_median, 4),
            "sharpe_per_trade": n_sharpe,
        },
        # 3.4 已實現/未實現分離:頂層(avg_return 等)含全部交易(向後相容,viewer 讀此),
        # realized = 真出場的交易,unrealized = end_of_data(回測窗末強制結算,未真出場)。
        # 混入 unrealized 會膨脹平均(例:mom v1 台化 +28.12% 未實現拉高毛均)。
        "realized": _return_stats([t for t in trades if t.exit_reason != "end_of_data"]),
        "unrealized": _return_stats([t for t in trades if t.exit_reason == "end_of_data"]),
        # 3.4 獨立標的數揭露:信賴區間應以獨立標的數計(非交易筆數;同一標的多次進出
        # 非獨立樣本)。此欄供報表/統計以正確 n 計算。
        "independent_tickers": len({t.ticker for t in trades}),
        "disclosure": _DISCLOSURE_NOTE,
        "cost_model": _cost_model_dict(),
        "equity_curve": equity_curve,
    }


def _count_reasons(trades: list[Trade]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in trades:
        out[t.exit_reason] = out.get(t.exit_reason, 0) + 1
    return out


# ── v2 partial-sizing engine ────────────────────────────────────────────────
# Adds 加碼/減碼/TP1 partial / ATR structural stop on top of the v1 chip-defined
# exits. ATR uses a CLOSE-TO-CLOSE proxy (snapshots carry open+close, no
# high/low) — documented in the result limitations.

def _wflags(rec: dict) -> set[str]:
    return {f.get("code") for f in ((rec or {}).get("weakening") or {}).get("flags", []) if f.get("code")}


def _seq_closes(seq: list[dict]) -> list[float]:
    return [r.get("current_price") for r in seq if r.get("current_price") is not None]


def _atr_pct(closes: list[float], window: int) -> float | None:
    if len(closes) < 2:
        return None
    diffs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))][-window:]
    if not diffs or not closes[-1]:
        return None
    return (sum(diffs) / len(diffs)) / closes[-1]


def _record_leg(result, pos, ticker, units, fill_price, exit_date, reason, holding_days):
    avg = pos["total_cost"] / pos["units"] if pos["units"] else 0.0
    ret = (fill_price - avg) / avg if avg else 0.0
    result.trades.append(Trade(
        ticker=ticker, name=pos["name"], entry_date=pos["entry_date"], entry_price=avg,
        exit_date=exit_date, exit_price=fill_price, return_pct=ret,
        exit_reason=reason, holding_days=holding_days, units=round(units, 2),
    ))
    frac = (pos["units"] - units) / pos["units"] if pos["units"] else 0.0
    pos["total_cost"] *= frac
    pos["units"] -= units


def _run_backtest_v2(snaps, dates, strategy, result):
    n = len(snaps)
    chip = strategy.kind == "chip_anchored"
    if chip:
        from core import golden as _golden
    result.limitations.append(
        "v2 partial sizing: 加碼/減碼/TP1 已實作; ATR 用收盤對收盤代理(快照無 high/low)")
    open_pos: dict[str, dict] = {}
    cooldown: dict[str, int] = {}    # 3.3: ticker -> 上次完全出場的 fill index(冷卻期防洗單)

    def _seq(ticker, upto):
        out = []
        for s in snaps[:upto]:
            for r in s.get("stocks", []):
                if r.get("ticker") == ticker:
                    out.append(r); break
        return out

    for i in range(n - 1):
        decide, fill = snaps[i], snaps[i + 1]
        prior = snaps[:i]

        for ticker in list(open_pos.keys()):
            pos = open_pos[ticker]
            rec = _rec_for(decide, ticker)
            price = rec.get("current_price") if rec else None
            if price is None:
                continue
            pos["peak"] = max(pos["peak"], price)
            fii = (rec.get("fii_net_buy") or 0)
            mfb = (rec.get("main_force_buy") or 0)
            pos["fii_neg_run"] = pos["fii_neg_run"] + 1 if fii < 0 else 0
            pos["mfb_neg_run"] = pos["mfb_neg_run"] + 1 if mfb < 0 else 0
            te = temporal_enrich(ticker, prior, rec)
            vel = te["velocity_3d"]
            pos["vel_neg_run"] = pos["vel_neg_run"] + 1 if (vel is not None and vel < 0) else 0
            sev = _weakening_sev(rec)
            flags = _wflags(rec)
            hd = (i + 1) - pos["entry_i"]
            fp = _fill_price(fill, ticker)
            if fp is None:
                continue

            # ---- full exit (TP2 / hard stop) ----
            full = None
            if sev in strategy.exit_on_weakening:
                full = "weakening_tp2"
            elif chip and "W3" in flags:
                full = "W3_hardstop"
            elif chip and pos["mfb_neg_run"] >= 2:
                full = "main_force_sell"
            elif not chip and pos["fii_neg_run"] >= strategy.fii_reversal_days:
                full = "fii_reversal"
            elif not chip and price <= pos["peak"] * (1 - strategy.trailing_stop_pct):
                full = "trailing_stop"
            elif chip:
                closes = _seq_closes(_seq(ticker, i + 1))
                cost = rec.get("main_force_cost") or pos.get("anchor")
                atrp = _atr_pct(closes, strategy.atr_window)
                slow = min(closes[-strategy.structure_low_window:]) if closes else None
                if cost and slow is not None and atrp is not None:
                    stop = max(cost, slow) * (1 - strategy.atr_buffer_mult * atrp)
                    if price <= stop:
                        # 3.1:此止損位 = max(主力成本, 近N日結構低)×(1−緩衝·ATR%)。
                        # 結構低點隨股價墊高會被抬到進場均價之上,獲利部位也會觸發
                        # ——那實為「移動停利」(trailing_stop),不是砍損的 atr_stop。
                        # 依出場報酬正負分標籤:虧損出場才記 atr_stop,獲利/打平出場
                        # 改標 trailing_stop(驗收:所有 atr_stop 出場報酬必為負)。
                        avg_cost = pos["total_cost"] / pos["units"] if pos["units"] else 0.0
                        full = "atr_stop" if fp < avg_cost else "trailing_stop"
            if full:
                _record_leg(result, pos, ticker, pos["units"], fp, dates[i + 1], full, hd)
                del open_pos[ticker]
                cooldown[ticker] = i + 1        # 3.3: 出場成交日 → 起算冷卻期
                continue

            # ---- TP1 partial (sell half, once) ----
            if not pos.get("tp1_done") and pos["units"] > 0.5:
                tp1 = False
                if chip:
                    big_sell = mfb < -(pos.get("accum_avg_buy") or 0) * strategy.tp1_sell_mult
                    tp1 = big_sell or pos["vel_neg_run"] >= 2 or bool(flags & {"W1", "W5"})
                if tp1:
                    _record_leg(result, pos, ticker, pos["units"] / 2, fp, dates[i + 1], "tp1", hd)
                    pos["tp1_done"] = True

            # ---- 減碼 (B: velocity 轉負連2 → 減半) ----
            if not chip and pos["units"] > 0.5 and pos["vel_neg_run"] >= strategy.velocity_negative_days \
                    and not pos.get("reduced"):
                _record_leg(result, pos, ticker, pos["units"] / 2, fp, dates[i + 1], "vel_reduce", hd)
                pos["reduced"] = True

            # ---- 加碼 ----
            if pos["units"] < strategy.max_units:
                if chip and not pos.get("scaled") and sev in ("none", "yellow"):
                    # 3.2 防向下攤平(鴻海 309→273.5 黑洞):三約束同時成立才加碼。
                    #  (1) 成本錨固定:回貼帶用 entry_cost_anchor(進場當日 main_force_cost,
                    #      不隨後續重算下修)——舊碼用當日重算 cost,股價下跌途中反覆成立。
                    #  (2) 禁向下攤平:加碼價 fp ≥ 前次進場價 × BACKTEST_ADD_MIN_PRICE_MULT。
                    #  (3) 動能仍在:velocity_3d > 0。
                    anchor = pos.get("entry_cost_anchor")
                    lo, hi = strategy.add_cost_band
                    if (anchor
                            and lo * anchor <= price <= hi * anchor
                            and fp >= pos["last_entry_price"] * BACKTEST_ADD_MIN_PRICE_MULT
                            and (vel or 0) > 0):
                        pos["total_cost"] += strategy.add_unit * fp
                        pos["units"] += strategy.add_unit
                        pos["scaled"] = True
                        pos["last_entry_price"] = fp
                elif not chip and (vel or 0) > 0 and (i - pos["last_add_i"]) >= strategy.add_cooldown_days:
                    prior_mfb = [r.get("main_force_buy") for r in _seq(ticker, i)
                                 if r.get("main_force_buy") is not None]
                    if prior_mfb and mfb > max(prior_mfb):     # 主力買超創新高
                        pos["total_cost"] += strategy.add_unit * fp
                        pos["units"] += strategy.add_unit
                        pos["last_add_i"] = i

        # ---- entries ----
        # 進場閘門共用 would_enter(治理紅線 5,與 v1/UI 同一實作);chip 型另留
        # golden_map 只為取 anchor(would_enter 已保證 chip 過閘者 ge 存在)。
        gres = None
        golden_map = {}
        if chip:
            gres = _golden.run(snaps[:i + 1])
            golden_map = {e.ticker: e for e in (gres.prime + gres.strong)}
        for rec in decide.get("stocks", []):
            ticker = rec.get("ticker")
            if not ticker or ticker in open_pos:
                continue
            if _in_cooldown(cooldown, ticker, i + 1):   # 3.3: 冷卻期內禁再進場
                continue
            ok, _reasons = would_enter(ticker, snaps[:i + 1], strategy, golden_result=gres)
            if not ok:
                continue
            anchor = None
            if chip:
                ge = golden_map.get(ticker)
                anchor = ge.cost_conservative if ge.cost_conservative is not None else ge.main_force_cost
            fp = _fill_price(fill, ticker)
            if fp is None:
                continue
            seq_now = _seq(ticker, i + 1)
            pos_buys = [r.get("main_force_buy") for r in seq_now
                        if (r.get("main_force_buy") or 0) > 0]
            open_pos[ticker] = {
                "units": strategy.position_unit, "total_cost": strategy.position_unit * fp,
                "peak": fp, "entry_i": i + 1, "entry_date": dates[i + 1], "name": rec.get("name", ""),
                "fii_neg_run": 0, "mfb_neg_run": 0, "vel_neg_run": 0,
                "scaled": False, "reduced": False, "tp1_done": False, "last_add_i": i + 1,
                "anchor": anchor,
                # 3.2: 加碼防護狀態 —— 成本錨固定為進場當日 main_force_cost(不重算);
                # last_entry_price 追蹤最近一次進場成交價(禁向下攤平的比較基準)。
                "entry_cost_anchor": rec.get("main_force_cost") if chip else None,
                "last_entry_price": fp,
                "accum_avg_buy": (sum(pos_buys) / len(pos_buys)) if pos_buys else 0.0,
            }

    # settle remaining
    last = snaps[-1]
    for ticker, pos in open_pos.items():
        fp = _fill_price(last, ticker)
        if fp is None or pos["units"] <= 0:
            continue
        _record_leg(result, pos, ticker, pos["units"], fp, dates[-1], "end_of_data",
                    (n - 1) - pos["entry_i"])

    result.summary = _summarize(result.trades, strategy)
    return result
