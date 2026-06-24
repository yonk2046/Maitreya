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
    exit_reason: str          # trailing_stop | weakening | fii_reversal | end_of_data
    holding_days: int

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["return_pct"] = round(self.return_pct, 4)
        d["entry_price"] = round(self.entry_price, 2)
        d["exit_price"] = round(self.exit_price, 2)
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
