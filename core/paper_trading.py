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

from core.market_context import temporal_enrich
from core.strategies import StrategyConfig


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


def _momentum_entry_ok(cfg: StrategyConfig, temporal: dict, rec: dict) -> bool:
    if temporal["main_force_consecutive_days"] < cfg.entry_streak_min:
        return False
    if cfg.require_velocity_positive and not ((temporal["velocity_3d"] or 0) > 0):
        return False
    if cfg.require_acceleration_positive and not ((temporal["acceleration"] or 0) > 0):
        return False
    if cfg.require_fii_aligned and not ((rec.get("fii_net_buy") or 0) > 0):
        return False
    return True


def _weakening_sev(rec: dict) -> str:
    return ((rec or {}).get("weakening") or {}).get("severity", "none")


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

    # iterate decision days i = 0..n-2 (fill on i+1)
    for i in range(n - 1):
        decide, fill = snaps[i], snaps[i + 1]
        prior = snaps[:i]            # strictly-before slice for temporal
        d_date = dates[i]

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

        # ---- new entries (decide on i, execute on i+1) ----
        golden_map = {}
        if chip:
            gres = _golden.run(snaps[:i + 1])           # golden list as of day i (no look-ahead)
            golden_map = {e.ticker: e for e in (gres.prime + gres.strong)}

        for rec in decide.get("stocks", []):
            ticker = rec.get("ticker")
            if not ticker or ticker in open_pos:
                continue
            if chip:
                ge = golden_map.get(ticker)
                if ge is None:
                    continue                            # not in 黃金名單 (gate 全過) on day i
                anchor = ge.cost_conservative if ge.cost_conservative is not None else ge.main_force_cost
                price_d = rec.get("current_price")
                if not anchor or not price_d or price_d > anchor * strategy.max_premium_ratio:
                    continue                            # 現價 > 主力成本 × 1.05 → skip
            else:
                temporal = temporal_enrich(ticker, prior, rec)
                if not _momentum_entry_ok(strategy, temporal, rec):
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


def _summarize(trades: list[Trade], strategy: StrategyConfig) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "win_rate": None, "avg_return": None,
                "median_return": None, "sharpe_per_trade": None,
                "avg_holding_days": None, "max_drawdown": None}
    rets = sorted(t.return_pct for t in trades)
    wins = sum(1 for r in rets if r > 0)
    n = len(rets)
    mean = sum(rets) / n
    median = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    # equity-curve max drawdown over sequential trades (entry order)
    eq, peak, mdd = 1.0, 1.0, 0.0
    for t in sorted(trades, key=lambda x: x.entry_date):
        eq *= (1 + t.return_pct)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    # Per-trade Sharpe = mean / sample-stdev of trade returns (risk-free ≈ 0
    # per trade). NOT annualised. Small-sample → noisy; treat as directional.
    sharpe = None
    if n >= 2:
        var = sum((r - mean) ** 2 for r in rets) / (n - 1)
        sd = var ** 0.5
        sharpe = round(mean / sd, 2) if sd > 0 else None
    return {
        "trades": n,
        "win_rate": round(wins / n, 4),
        "avg_return": round(mean, 4),
        "median_return": round(median, 4),
        "sharpe_per_trade": sharpe,
        "avg_holding_days": round(sum(t.holding_days for t in trades) / n, 2),
        "max_drawdown": round(mdd, 4),
        "exit_reasons": _count_reasons(trades),
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
                        full = "atr_stop"
            if full:
                _record_leg(result, pos, ticker, pos["units"], fp, dates[i + 1], full, hd)
                del open_pos[ticker]
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
                    cost = rec.get("main_force_cost")
                    lo, hi = strategy.add_cost_band
                    if cost and lo * cost <= price <= hi * cost:
                        pos["total_cost"] += strategy.add_unit * fp
                        pos["units"] += strategy.add_unit
                        pos["scaled"] = True
                elif not chip and (vel or 0) > 0 and (i - pos["last_add_i"]) >= strategy.add_cooldown_days:
                    prior_mfb = [r.get("main_force_buy") for r in _seq(ticker, i)
                                 if r.get("main_force_buy") is not None]
                    if prior_mfb and mfb > max(prior_mfb):     # 主力買超創新高
                        pos["total_cost"] += strategy.add_unit * fp
                        pos["units"] += strategy.add_unit
                        pos["last_add_i"] = i

        # ---- entries ----
        golden_map = {}
        if chip:
            gres = _golden.run(snaps[:i + 1])
            golden_map = {e.ticker: e for e in (gres.prime + gres.strong)}
        for rec in decide.get("stocks", []):
            ticker = rec.get("ticker")
            if not ticker or ticker in open_pos:
                continue
            anchor = None
            if chip:
                ge = golden_map.get(ticker)
                if ge is None:
                    continue
                anchor = ge.cost_conservative if ge.cost_conservative is not None else ge.main_force_cost
                price_d = rec.get("current_price")
                if not anchor or not price_d or price_d > anchor * strategy.max_premium_ratio:
                    continue
            else:
                te = temporal_enrich(ticker, prior, rec)
                if not (te["main_force_consecutive_days"] >= strategy.entry_streak_min
                        and (te["velocity_3d"] or 0) > 0 and (te["acceleration"] or 0) > 0
                        and (rec.get("fii_net_buy") or 0) > 0):
                    continue
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
