# Maitreya — Architecture Reference
**For AI assistants and human reviewers joining this project.**  
Last updated: 2026-05-30 | Current phase: P3a-Hardening (P3b gated)

> *彌勒觀市，不測，只記。*  
> Maitreya watches the market. It does not predict. It only remembers.

---

## 0. What This System Does (30-second version)

Maitreya is a **Taiwan stock market observation terminal**. It ingests daily broker-desk ("分點") data from multiple upstream sources, runs it through a multi-layer scoring pipeline, and renders a bilingual (ZH/EN) Streamlit dashboard for human review.

**Critical constraint throughout the entire codebase:** Pure observation only. No trading signals, no buy/sell recommendations. Every output is a descriptive label derived deterministically from inputs.

The system answers one question: *which stocks are exhibiting sustained, institutional-grade accumulation behaviour across multiple time windows?*

---

## 1. Repo Layout

```
SCD engine/                        ← project root
├── tools/                         ← upstream fetchers (run OUTSIDE Ai stock/)
│   ├── fetch_daily.py             ← orchestrates Steps 1-9; writes data/today.json
│   ├── fetch_market_pulse.py      ← TAIEX + TX futures + 三大法人台指期 → data/market_pulse.json
│   ├── fetch_fubon.py             ← Fubon ZGK broker-desk scraper
│   ├── fetch_twse.py              ← TWSE open data (T86 institutional flow)
│   ├── fetch_sinotrade.py         ← Sinotrade branch data (broker-level positions)
│   └── fetch_tdcc.py              ← TDCC shareholder distribution
│
├── data/
│   ├── today.json                 ← latest raw fetch output
│   ├── market_pulse.json          ← TAIEX / TX futures / 三大法人 snapshot
│   └── (snapshots/, branches/)   ← rollup raw files; per-ticker branch JSON
│
└── Ai stock/                      ← Python package root (add to sys.path)
    ├── core/                      ← pure-Python intelligence layer (no I/O)
    │   ├── watchlists.py          ← TIER_A (8 anchors), SECTOR_GROUPS, helpers
    │   ├── market_context.py      ← 5 stateless observation functions
    │   ├── funnel.py              ← STEP 5: 5-layer candidate filter
    │   ├── state_machine.py       ← STEP 6: 9-state lifecycle per ticker
    │   ├── golden.py              ← STEP 7: Golden Layer v2 (conviction tiers)
    │   ├── confidence.py          ← STEP 8: 2D confidence × risk profiles
    │   ├── narrative_engine.py    ← bilingual market narrative text
    │   ├── market_state.py        ← unified market state (P3d)
    │   ├── sector_intelligence.py ← sector-level analysis helpers
    │   ├── ingest.py              ← raw JSON → canonical snapshot schema
    │   ├── archive.py             ← WORM-style archive writer
    │   ├── hashing.py             ← SHA-256 provenance sidecar
    │   └── worm_check.py          ← tamper detection
    │
    ├── data/
    │   ├── adapters/              ← legacy / rollup / contract adapters
    │   └── branches/<ticker>.json ← per-ticker Sinotrade branch history
    │
    ├── reports/
    │   ├── YYYY-MM-DD.json        ← canonical snapshots (one per trading day)
    │   ├── YYYY-MM-DD.sha256      ← hash sidecars
    │   ├── index.json             ← supersedes chain + metadata
    │   └── _raw_archive/<date>/   ← immutable provenance files
    │
    ├── tools/
    │   ├── daily.py               ← daily pipeline orchestrator
    │   ├── run_pipeline.py        ← single-date ingest entrypoint
    │   └── temporal/              ← read-only temporal analysis toolkit
    │       ├── _loader.py         ← CLI-safe snapshot loader (no streamlit)
    │       ├── streak_analyzer.py
    │       ├── transition_detector.py
    │       ├── persistence_ranker.py
    │       ├── regime_monitor.py
    │       └── market_flow_monitor.py
    │
    ├── viewer/
    │   ├── cockpit.py             ← PRIMARY UI — 10-tab dashboard on :8502
    │   ├── cockpit_v2.py          ← experimental v2 on :8503 (same features)
    │   ├── app.py                 ← engineering diagnostic viewer on :8501
    │   ├── data.py                ← Streamlit-aware snapshot loader + cache
    │   ├── intelligence.py        ← legacy scoring layer (still used by app.py)
    │   └── metrics.py             ← metric computation helpers
    │
    ├── tests/                     ← pytest suite
    ├── Makefile                   ← all entrypoints (see Section 5)
    └── ARCHITECTURE.md            ← this file
```

---

## 2. Data Flow

```
Upstream sources
  Fubon ZGK (broker-desk)
  TWSE T86 (institutional flow)
  Sinotrade (branch positions)
  TDCC (shareholder distribution)
        │
        ▼
tools/fetch_daily.py  ─────────────────────────────► data/today.json
tools/fetch_market_pulse.py ────────────────────────► data/market_pulse.json
        │
        ▼
core/ingest.py  (normalize → canonical schema)
core/hashing.py (SHA-256 sidecar)
core/archive.py (WORM write)
        │
        ▼
reports/YYYY-MM-DD.json   ←  one file per trading day
reports/index.json        ←  supersedes chain
        │
        ▼
tools/temporal/_loader.py  (CLI-safe multi-snapshot loader)
viewer/data.py             (Streamlit-cached loader)
        │
        ├──► core/market_context.py  (stateless, 5 functions)
        │
        ├──► core/funnel.py          ─┐
        ├──► core/state_machine.py    ├─► core/golden.py ──► core/confidence.py
        │                             │
        └──► tools/temporal/*  ───────┘  (read-only temporal analysis)
                │
                ▼
        viewer/cockpit.py  (Streamlit, port 8502)
        10 tabs: Regime / Radar / Strengthening / Failed Breakout /
                 Accumulation / Rotation / Temporal / Narrative /
                 ★ Golden Layer / ◈ Confidence & Risk
```

**Key rule:** `tools/temporal/_loader.py` must never import streamlit. It's the CLI-safe path. `viewer/data.py` is the Streamlit-cached path. Both load from `reports/`.

---

## 3. The Intelligence Pipeline (STEPS 5–8)

Each layer receives snapshots and produces a typed dataclass result. They are designed to be called sequentially, but currently each re-runs the layers below it independently (known duplication — see Section 7).

### STEP 5 — Funnel (`core/funnel.py`)

Five ordered gates. A ticker passes when it clears all gates above its current layer.

```
DISCOVERY      ← appeared in ≥1 snapshot this window
OBSERVATION    ← streak ≥ 1 (appeared in last snapshot)
CONFIRMATION   ← streak ≥ 2 AND net_cumulative > 0
RISK_WARNING   ← failed_breakout detected
FAILURE        ← streak = 0 after confirmed status
```

Public API: `run_all(snaps) → dict[ticker, FunnelResult]`

### STEP 6 — State Machine (`core/state_machine.py`)

Nine lifecycle states, evaluated per ticker over the full snapshot window.

```
UNDISCOVERED → DISCOVERED → ACCUMULATING → STRENGTHENING
                                                 │
                                          DISTRIBUTING (early exit warning)
                                                 │
                                          CONFIRMED → EXTENDED → EXITED
                                                 │
                                              FAILED
```

Key state logic:
- `DISTRIBUTING`: was_strong AND (velocity_negative OR accel_negative)
- `CONFIRMED`: funnel=confirmation AND streak≥3 AND sponsorship≥0.45
- `EXTENDED`: confirmed + additional 5 days
- Transition risk: `low / medium / elevated / critical` (4 levels)

Public API: `run_all(snaps) → dict[ticker, TickerState]`, `state_summary(snaps) → dict`

### STEP 7 — Golden Layer (`core/golden.py`)

Five gates + weighted conviction score → three tier labels.

**Gates:**
- G1: funnel layer = confirmation
- G2: SM state ∈ {confirmed, strengthening}
- G3: sponsorship_score ≥ 0.45
- G4: transition_risk ≠ critical
- G5: net_cumulative > 0

**Conviction score** (additive, capped at 1.0):
streak≥5 +0.40, streak≥3 +0.15, spon≥0.70 +0.30, spon≥0.55 +0.10,
confirmed +0.15, tier_a +0.10, velocity_pos +0.10, accel_pos +0.05, sector_top3 +0.05

**Tiers:** PRIME ≥ 0.65 · STRONG ≥ 0.40 · QUALIFIED ≥ 0.0
**Near-miss:** passed exactly 4 of 5 gates

Public API: `run(snaps) → GoldenResult`

`GoldenResult` fields: `date, snapshot_count, prime, strong, qualified, near_miss`
`GoldenEntry` key fields: `ticker, name, tier, conviction, gates_passed, sponsorship_score, streak, sm_state_zh`

### STEP 8 — Confidence & Risk (`core/confidence.py`)

Two independent 0.0–1.0 scores per ticker → 7 profile codes.

**Confidence** components (additive, capped 1.0):
streak/10 →max 0.30, sponsorship×0.25, velocity_pos +0.15, accel_pos +0.10,
in_golden +0.15, conviction×0.05, sector_top3 +0.05, tier_a +0.05

**Risk** components (additive, uncapped before classification):
sm_base (critical→0.40, elevated→0.25, medium→0.10),
distributing +0.25, funnel_warning +0.20, failed_breakout +0.20,
velocity_neg +0.15, accel_strongly_neg +0.10, streak_zero +0.10

**Profile codes:** `high_low, high_medium, high_elevated, mid_low, mid_elevated, low_any, deteriorating`

**Market Risk Temperature** (`MarketRiskTemperature`):
`temperature = 0.40×elevated_ratio + 0.30×distributing_ratio + 0.30×breadth_risk`
Levels: `cool / stable / warm / hot / extreme`

Public API: `run(snaps) → ConfidenceResult`

`ConfidenceResult` fields: `date, snapshot_count, market_temperature, profiles (dict), ideal, watch, deteriorating, weak`
`ConfidenceProfile` key fields: `ticker, name, confidence, risk_score, profile_code, profile_zh, risk_level, risk_zh, sm_state_zh, golden_conviction, streak`
`MarketRiskTemperature` key fields: `temperature, temperature_level, temperature_zh, temperature_color`

---

## 4. Canonical Snapshot Schema

Each `reports/YYYY-MM-DD.json` has this top-level shape:

```json
{
  "date": "YYYY-MM-DD",
  "universe_size": 30,
  "schema_version": "2.0",
  "generated_at": "ISO-8601",
  "provenance": { "source": "rollup", "canonical_hash": "sha256:..." },
  "market_regime": { "breadth": 0.62, "avg_chg": 0.38, "vol_index": 1.2 },
  "stocks": [
    {
      "ticker": "2317",
      "name": "鴻海",
      "current_price": 185.5,
      "change_pct": 1.2,
      "main_force_buy": 3200,
      "main_force_cost": 182.3,
      "top5_branches": ["凱基台北", "元大板橋"],
      "fii_holding_trend_5d": null
    }
  ],
  "audit_log": [...]
}
```

`main_force_buy` is in 張 (1張 = 1000 shares). Positive = net buy, negative = net sell.  
`top5_branches` are broker-desk names from Sinotrade data.

---

## 5. Key Make Targets

```bash
# UI
make cockpit              # launch primary dashboard on :8502 (recommended)
make restart-cockpit      # kill any running streamlit → relaunch :8502

# Daily data pipeline
make fetch                # upstream fetch → data/today.json
make fetch-pulse          # TAIEX/TX/三大法人 → data/market_pulse.json
make daily                # full daily flow: fetch → ingest → verify-all-replay

# Intelligence pipeline (CLI)
make funnel               # STEP 5: candidate funnel output
make state-machine        # STEP 6: lifecycle states for all tickers
make golden               # STEP 7: golden layer (prime/strong/qualified)
make golden-near-miss     # STEP 7: include near-miss entries
make confidence           # STEP 8: 2D confidence/risk + market temperature

# Temporal toolkit (read-only)
make streak-analyze       # persistence rows across snapshot archive
make transitions          # state transitions across consecutive snapshots
make market-flow          # regime + capital flow + leadership rotation

# Integrity
make test                 # full pytest suite
make verify-replay DATE=YYYY-MM-DD
make verify-index         # integrity scan over reports/index.json
make fix-index            # idempotent supersedes-chain repair
```

---

## 6. Core Design Decisions

**A. Pure-function intelligence layer**  
All of `core/` (except ingest/archive/worm) is stateless and I/O-free. They take `snaps: list[dict]` and return typed dataclasses. This makes them testable without any database or file system. The Streamlit UI is a thin shell on top.

**B. WORM provenance**  
Once a snapshot is archived, it cannot be modified — only superseded. `reports/index.json` maintains a `supersedes` chain. `worm_check.py` verifies SHA-256 sidecars on startup.

**C. Temporal-first scoring**  
The system's primary value is *time-series behaviour*, not single-day scores. `streak`, `velocity_3d`, `acceleration`, and `sponsorship_persistence` are multi-day sliding-window metrics. A ticker appearing once with a high score is less interesting than one appearing consistently for 5+ days.

**D. Bilingual output**  
Every classification label has both `_zh` and `_en` variants in the dataclass. The UI renders both. This is structural — not just translation.

**E. CLI-safe vs Streamlit-safe imports**  
`tools/temporal/_loader.py` must never import streamlit. Any CLI entrypoint (`-m core.golden`, `make funnel`) must use `_loader.py`, never `viewer/data.py`.

**F. Dataclass field ordering**  
Python 3.10 dataclasses: all non-default fields must precede all fields with defaults. `float | None` union syntax is used throughout. Two bugs were caused by violating this — always put `field(default_factory=...)` and `= value` fields last.

---

## 7. Known Architecture Debt

These are documented and intentional trade-offs, not bugs:

| Issue | Location | Impact | Recommended fix |
|-------|----------|--------|-----------------|
| `state_machine.run_all()` called 3× per `confidence.run()` | confidence.py | CPU only; mitigated by `@st.cache_data(ttl=120)` | Add optional `sm_result=` param to golden/confidence |
| `funnel.run_all()` called twice inside confidence (via golden) | confidence.py | Same as above | Pass funnel result through |
| `accumulation_velocity()` computed independently in funnel, state_machine, confidence | all three | Same data, three passes | Shared `MetricsCache` per ticker |
| Sector top-3 logic: 3 independent implementations | funnel, state_machine, golden | Slight divergence possible | Add `sector_top3: bool` to `TickerState` |
| `_is_deteriorating()` re-runs `accumulation_velocity` on prev_records | confidence.py | One extra pass per ticker | Use `sm_state.velocity_3d` directly |

---

## 8. Streamlit UI — Tab Map (cockpit.py, :8502)

| # | Tab label | Data source | Key output |
|---|-----------|-------------|------------|
| 1 | 📊 市場體制 | `market_context.regime_shift()` | Regime banner, breadth/avg-chg charts |
| 2 | 🎯 雷達觀察 | `market_context.full_ticker_context()` | Tier A 5-card grid (TSMC, Hon Hai, MediaTek, Delta, Quanta) |
| 3 | ↑ 轉強訊號 | `full_ticker_context()` streak≥2 | Cards with streak/velocity/sponsorship tags |
| 4 | ⚠ 假突破 | `failed_breakout_memory()` | Warning cards with breakout date/vol/retreat |
| 5 | ◉ 持續吸籌 | `sponsorship_persistence()` ≥0.35 | Progress bar + broker info |
| 6 | ⟳ 資金輪動 | `leadership_rotation()` | Sector flow bars + 5-day trend chart |
| 7 | ⌛ 時序演化 | raw snapshots | Single-ticker chain view OR multi-ticker heatmap |
| 8 | 📰 市場敘事 | `narrative_engine.generate()` | Bilingual narrative bullets + themes + entities |
| 9 | ★ 黃金名單 | `golden.run()` | PRIME/STRONG/QUALIFIED tier cards + near-miss expander |
| 10 | ◈ 信心風險 | `confidence.run()` | Temperature banner + 2D scatter + profile cards |

Cache strategy: `@st.cache_data(ttl=120)` keyed on `f"{last_date}_{len(snaps)}"` (cheap, no hashing).

---

## 9. Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| P3a | ✅ shipped | Core pipeline: ingest → archive → WORM → replay verification |
| P3a-Hardening | 🔄 in progress | Integrity tests, provenance audit, index repair |
| P3b | ⏳ gated | Scoring layer: tier / composite_score (currently all IGNORE/0) |
| P3c | ✅ shipped | Market context: regime + rotation + narrative + watchlists |
| P3d | ✅ shipped | Unified market state engine |
| P3e | ✅ shipped | Candidate funnel (STEP 5) + state machine (STEP 6) |
| P3f | ✅ shipped | Golden Layer v2 (STEP 7) |
| P3g | ✅ shipped | Confidence & Risk profiles (STEP 8) |
| P3h (next) | 🔲 planned | STEP 9: AI Commentary layer (narrative from Golden+Confidence) |

P3b requires ≥20 days of snapshot history and explicit sign-off before enabling real scores — currently all tickers carry `tier=IGNORE`, `composite_score=0`.

---

## 10. How to Review This Project

### Quick orientation (5 minutes)
```bash
cd "SCD engine/Ai stock"
make golden              # run the full golden layer, read the output
make confidence          # run confidence/risk, see market temperature
make cockpit             # launch UI at http://127.0.0.1:8502
```

### Read these files in order
1. `core/watchlists.py` — understand the universe (Tier A, sector groups)
2. `core/market_context.py` — the 5 primitive observation functions
3. `core/funnel.py` — how candidates are filtered
4. `core/state_machine.py` — lifecycle state logic
5. `core/golden.py` — conviction scoring and tier gates
6. `core/confidence.py` — 2D confidence/risk + market temperature
7. `viewer/cockpit.py` — how the UI consumes all of the above

### Run the test suite
```bash
make test       # full pytest suite
make test-fast  # quick run
```

### Things to look for in a review
- Are the gate thresholds in `golden.py` defensible? (G3: spon≥0.45, PRIME: conviction≥0.65)
- Is the risk scoring in `confidence.py` well-calibrated? (DISTRIBUTING adds +0.25 risk)
- Does the state machine's DISTRIBUTING detection catch real distribution early enough?
- Are there edge cases in `failed_breakout_memory()` with thin-volume days?
- Is the 3× `state_machine.run_all()` duplication worth fixing before P3h?

---

*This document describes the system as of 2026-05-30, after STEP 8 (Confidence & Risk) delivery.*  
*Next session should start from STEP 9: AI Commentary, or P3a-Hardening sign-off.*
