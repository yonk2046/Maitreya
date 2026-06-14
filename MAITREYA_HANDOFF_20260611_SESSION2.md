# Maitreya Engine — Handoff Document
**Session**: 2026-06-11 (Session 2, context continuation from Session 1)
**Commit at handoff**: `ea79869`
**Test baseline**: 117 passed / 4 pre-existing failures
**Branch**: `main` (single-branch repo)

---

## What This Project Is

**Maitreya** is a deterministic SCD (Stock Condition Detection) engine for TWSE stocks. It is in **P3a mode** (Ingest-Only): the full 5-stage funnel, state machine, and scoring are all built and tested but scoring is intentionally **abstained** — `composite_score = 0`, `tier = "IGNORE"` for every stock. The goal of P3a is to validate the entire plumbing (replay-safe canonical hashing, lookback chains, provenance) before activating any scoring.

**Key invariants:**
- `data/today.json`, `data/branches/`, `data/snapshots/` are **WORM** — the pipeline reads them but never writes them during the adapter phase.
- `data/tdcc/` is NOT WORM — it is written by `tools/fetch_tdcc.py` before the main pipeline runs.
- Every snapshot has a `canonical_sha256` for replay safety. The index at `reports/index.json` tracks the full hash history per date.

---

## Repository Layout

```
Ai stock/
├── core/                    # All engine logic
│   ├── ingest.py            # ★ MODIFIED THIS SESSION — schema v1.5
│   ├── golden.py            # ★ MODIFIED THIS SESSION — SKELETON gate
│   ├── funnel.py            # 5-stage funnel (P3a: abstained)
│   ├── state_machine.py     # SM states (P3a: abstained)
│   ├── confidence.py        # Confidence + risk profiles
│   ├── distribution.py      # Distribution Intelligence Layer (sidecar)
│   ├── hashing.py           # canonical_sha256, file_sha256
│   └── ...
├── data/
│   ├── adapters/
│   │   ├── legacy.py        # ★ MODIFIED THIS SESSION — raw_sha256 fix + TDCC wire-up
│   │   ├── tdcc_adapter.py  # ★ NEW last session — TDCC 集保 weekly data
│   │   ├── rollup.py        # Rollup adapter (reads reports/ snapshots)
│   │   └── contract.py      # Adapter output contract validator
│   ├── branches/            # Per-branch buy/sell data (WORM)
│   ├── tdcc/
│   │   └── 20260605.json    # ★ NEW — TDCC cache, 3,989 securities
│   └── today.json           # Daily market data (WORM, written by fetch_daily.py)
├── tools/
│   ├── fetch_daily.py       # Main daily fetch orchestrator (runs via launchd + GHA)
│   └── fetch_tdcc.py        # TDCC fetcher (thin wrapper around tdcc_adapter)
├── tests/
│   ├── test_schema_v15.py   # ★ NEW this session — 20 tests for v1.5 fields
│   ├── test_tdcc_adapter.py # ★ MODIFIED this session — fixed no-cache test
│   └── ...
├── reports/
│   ├── index.json           # ★ FIXED this session — hash drift for Jun 9-11 aligned
│   └── YYYY-MM-DD.json      # Canonical snapshots (schema v1.4.0 on disk; v1.5 from next run)
├── config/
│   └── scd.example.yaml     # Config file (tier thresholds, validation settings)
├── .github/workflows/
│   └── daily.yml            # GHA: runs Mon-Fri 11:00 UTC, commits data/ + reports/
└── MAITREYA_HANDOFF_20260611.md  # Session 1 handoff (the original)
```

---

## What Was Done This Session

### Bug: `_project_root()` resolving to wrong directory (FIXED, `dc0b286`)
The anchor-file check (`tools/fetch_daily.py` + `data/` siblings) now runs FIRST, before the loose parent-directory check that was matching `SCD engine/` instead of `Ai stock/`.

### P0: TDCC Adapter (`data/adapters/tdcc_adapter.py`) (SHIPPED, `a2f618c`)

Full adapter for TDCC 集保股權分散表 (Taiwan Depository & Clearing Corp weekly distribution data). Grade mapping:
- Grade 12–15 (≥ 400 lots = ≥ 400,000 shares) → `large_holder_400_pct`
- Grade 15 only (≥ 1,000 lots) → `large_holder_1000_pct`
- Grade 17 (total row) → `shareholder_count`

Provides week-over-week deltas for all three fields. Cache: `data/tdcc/<YYYYMMDD>.json`. Bootstrap file `20260605.json` contains 3,989 securities.

**TDCC URL**: `https://opendata.tdcc.com.tw/getOD.ashx?id=1-5&key=Open` (CSV, ~2MB, published every Friday after market close).

### P1: Schema v1.5 (SHIPPED, `ea79869`)

**`core/ingest.py`** — SCHEMA_VERSION bumped to `"1.5.0"`:

Five new fields on every stock record:

| Field | Type | P3a Value | P3b Value (future) |
|---|---|---|---|
| `data_completeness` | `float` (0–1) | computed | same |
| `confidence_tier` | `str` | computed | same |
| `momentum_direction` | `str` | `"unknown"` | accelerating/decelerating/reversing/steady |
| `signal_age_days` | `int` | `1` | days in current tier |
| `delta_vs_yesterday` | `str` | `"—"` | +N / -N / NEW / — |

**`data_completeness`** is the fraction of 11 key fields that are non-None:
```python
_COMPLETENESS_FIELDS = (
    "current_price", "volume", "change_pct", "fii_net_buy", "main_force_buy",
    "large_holder_400_pct", "large_holder_1000_pct", "shareholder_count",
    "margin_balance", "broker_count_diff", "top5_concentration",
)
```

**`confidence_tier`** thresholds:
- `FULL` — completeness ≥ 0.80
- `PARTIAL` — completeness 0.50–0.80
- `SKELETON` — completeness < 0.50

**Typical values in P3a** (with TDCC cache present, T86 FII data):
- `current_price` ✓ + `change_pct` ✓ + `volume` ✓ + `fii_net_buy` ✓ + `main_force_buy` ✓ + TDCC 3 fields ✓ = 8/11 → 0.727 → **PARTIAL**
- Without TDCC: 5/11 = 0.454 → **SKELETON**

**`core/golden.py`** — SKELETON gate:
```python
if stock_data.get("confidence_tier") == "SKELETON" and tier == TIER_PRIME_KEY:
    tier = TIER_STRONG_KEY
```
Data-thin tickers cannot reach PRIME. Only SKELETON is gated; PARTIAL and FULL can reach PRIME normally.

### Bug Fix: TDCC fields dropped by `_abstain_stock_record` (FIXED, `ea79869`)

`core/ingest.py` was hardcoding `shareholder_count`, `large_holder_400_pct`, etc. to `None` instead of reading from `raw`. The TDCC adapter correctly enriched `raw_inputs_per_ticker`, but the ingest layer silently dropped the data. Now correctly wired:
```python
"shareholder_count":       raw.get("shareholder_count"),
"large_holder_400_pct":    raw.get("large_holder_400_pct"),
# ... etc.
```

### Bug Fix: `raw_sha256: None` violating contract (FIXED, `ea79869`)

`data/adapters/legacy.py` was setting `provenance_sources["tdcc_weekly"]["raw_sha256"] = None`. The contract validator requires `sha256:<64hex>`. Fixed to `file_sha256(tdcc_dir / f"{sample['tdcc_date']}.json")`.

### Index Hash Drift (FIXED, `ea79869`)

Reports for 2026-06-09, 2026-06-10, 2026-06-11 had a hash mismatch between `reports/index.json` and the actual on-disk files (caused by the two-pipeline race — see below). Fixed by adding reconciliation history entries pointing to the actual disk hashes.

---

## Current Test Baseline

**117 passed / 4 failed** (4 failures are pre-existing, unrelated to our work):

| Failure | Root Cause | Action Needed |
|---|---|---|
| `test_rollup_adapter_satisfies_contract_for_every_available_date` | `data/snapshots/` directory doesn't exist | Rollup adapter not yet plumbed; skip or create dir |
| `test_every_snapshot_matches_canonical_schema` | `*.intelligence.json` sidecars missing `schema_version`, `config_hash`, `core_version` | Distribution Layer sidecar schema needs updating |
| `test_every_sidecar_matches_canonical_hash` | Same sidecars missing | Same fix |
| `test_index_covers_all_real_snapshots_on_disk` | Intelligence sidecars not indexed | Same fix |

**The 4 failures are all about `*.intelligence.json` sidecars** (Distribution Layer reports) not conforming to the canonical snapshot schema. These were generated before schema requirements were formalized. Fix: either update `core/distribution.py` to emit the required top-level fields, or update the test to skip sidecar files for schema validation.

---

## The Two-Pipeline Problem

This repo has **two concurrent pipelines** both committing to `main`:
1. **Local launchd** — runs `make daily` on the user's Mac (schedule unknown, appears to run daily)
2. **GitHub Actions** (`daily.yml`) — runs Mon–Fri at 11:00 UTC

Both pipelines generate `reports/YYYY-MM-DD.json` and update `reports/index.json`, then push to `main`. This causes **non-fast-forward rejections** almost every day. The pattern:

```bash
# Pull first, then push
git pull --rebase origin main
# If branches data conflict:
git checkout --theirs data/branches/NNNN.json  # for each conflicting file
git add data/ reports/
git rebase --continue
git push
```

**The GHA pipeline handles this** with `git pull --rebase` before push (see `daily.yml` lines 44-46). The local pipeline may not always handle it gracefully. This is an ongoing operational friction point, not a code bug.

---

## Architecture: How the Pipeline Works

```
[daily run]
     │
     ├─ tools/fetch_daily.py        ← fetch today.json + branches + T86
     │       ├─ Step 5: tdcc_adapter.fetch_and_save()  (idempotent, ~2MB)
     │       └─ emit progress to console
     │
     ├─ data/adapters/legacy.py::adapt_legacy()
     │       ├─ Read today.json + branches + T86 merge
     │       ├─ TDCC enrich: tdcc_adapter.load_for_date() + enrich_universe()
     │       └─ Return raw_inputs_per_ticker + provenance_sources
     │
     ├─ core/ingest.py::ingest()
     │       ├─ Build StockRecord per ticker (_abstain_stock_record)
     │       │     ├─ All scoring: abstained (P3a)
     │       │     └─ NEW v1.5: data_completeness, confidence_tier, ...
     │       └─ Return canonical snapshot dict (schema v1.5.0)
     │
     └─ [write] reports/YYYY-MM-DD.json + update reports/index.json
```

**TDCC refresh cadence**: TDCC publishes data every Friday. `fetch_and_save()` is idempotent — it skips download if today's cache already exists. It finds the nearest cache on or before `target_date` for enrichment (max lag = 7 days by config).

---

## Schema v1.5.0 Stock Record — Key Fields

```json
{
  "ticker": "2330",
  "name": "台積電",
  "market": "TWSE",
  "data_completeness": 0.7273,
  "confidence_tier": "PARTIAL",
  "momentum_direction": "unknown",
  "signal_age_days": 1,
  "delta_vs_yesterday": "—",
  "current_price": 980.0,
  "fii_net_buy": 1234,
  "main_force_buy": 5678,
  "shareholder_count": 571234,
  "shareholder_count_delta_pct": 0.15,
  "large_holder_400_pct": 96.8,
  "large_holder_400_delta_pct": 0.12,
  "large_holder_1000_pct": 94.2,
  "large_holder_1000_delta_pct": 0.08,
  "composite_score": 0,
  "tier": "IGNORE",
  "temporal_state": {
    "abstained": {"velocity": true, "acceleration": true, "trend": true,
                  "reason": "P3a ingest-only; no scoring computed yet"}
  }
}
```

**Note**: On-disk snapshots in `reports/` still show `schema_version: "1.4.0"` because they were generated before today's changes. The next pipeline run will produce v1.5.0 snapshots.

---

## Constants and Thresholds (core/golden.py)

```python
TIER_PRIME     = 0.65   # conviction threshold for PRIME
TIER_STRONG    = 0.45   # conviction threshold for STRONG
TIER_PRIME_KEY = "prime"
TIER_STRONG_KEY = "strong"
TIER_QUALIFIED_KEY = "qualified"
```

Conviction is computed from: streak, sponsorship, SM state, velocity, acceleration, sector rank, Tier A membership.

---

## Security Note — GitHub Tokens

THREE GitHub tokens have been observed across sessions. **NEVER reproduce them in any output.** Always redact with:
```bash
sed 's#ghp_[A-Za-z0-9]*#ghp_***REDACTED***#g'
```

---

## Known Issues / Technical Debt

1. **`.intelligence.json` sidecar schema** — 14 intelligence sidecar files (May) don't have `schema_version`, `config_hash`, `core_version`. The test `test_every_snapshot_matches_canonical_schema` fails because of this. Fix: update `core/distribution.py` to add these fields, or add an `intelligence_schema_version` to sidecars and update the test's schema validator to handle both shapes.

2. **`data/snapshots/` missing** — `data/adapters/rollup.py` expects this directory. The rollup adapter (`adapt_rollup()`) is not plumbed into the daily pipeline yet. Either create the dir (with a `.gitkeep`) or skip the test.

3. **`momentum_direction` = "unknown"** — Stub until P3b scoring activates. When P3b lands, wire to `temporal_state.score_velocity` and `score_acceleration`:
   - velocity > 0 AND acceleration > 0 → `"accelerating"`
   - velocity > 0 AND acceleration ≤ 0 → `"decelerating"`
   - velocity < 0 → `"reversing"`
   - else → `"steady"`

4. **`delta_vs_yesterday` = "—"** — Stub until P3b. Will compare `composite_score` (or tier rank) to prior day's snapshot. Requires loading the prior day's `reports/YYYY-MM-DD.json` during ingest.

5. **`signal_age_days` = 1** — Always 1 in P3a because `tier_in_current_state_days` is always bootstrapped to 1 (no prior scoring to track tier transitions). Will become meaningful when scoring activates.

6. **Two-pipeline index race** — Addressed by a one-time fix today (Jun 9-11 alignment). Will recur whenever the two pipelines generate different content for the same date.

---

## What Comes Next (P3b Gate Criteria)

P3b (activating scoring) is **gated** until P3a-Hardening is signed off:
- ≥ 20 trading days of stable P3a snapshots with no replay mismatches
- `B1` bug (undefined, tracked elsewhere) must be fixed
- Distribution Layer sidecar schema issues resolved (4 pre-existing test failures)

Once P3b activates, the stub fields (`momentum_direction`, `delta_vs_yesterday`, `signal_age_days`) need to be wired to real data.

---

## How to Run Locally

```bash
# Daily pipeline (fetch + ingest + write snapshot)
make daily

# TDCC cache refresh (run on Fridays, or manually)
python3 -m tools.fetch_tdcc

# Tests
python3 -m pytest                    # full suite (117 pass, 4 pre-existing fail)
python3 -m pytest tests/test_schema_v15.py    # v1.5 fields (20 tests)
python3 -m pytest tests/test_tdcc_adapter.py  # TDCC adapter (18 tests)
python3 -m pytest tests/test_replay.py        # replay safety (9 tests)

# Push (always pull first to avoid non-fast-forward)
git pull --rebase origin main && git push
```

---

## Next Steps — Backlog (Priority Order)

### 🔴 P3a-Hardening (MUST complete before P3b)

These block scoring activation. Do them in order.

**H1 — Fix intelligence sidecar schema (4 pre-existing test failures)**
- Files: `core/distribution.py`, `tests/test_contracts.py`
- Problem: `reports/2026-05-*.intelligence.json` sidecars missing `schema_version`, `config_hash`, `core_version`. The contract schema validator rejects them.
- Fix option A: Add the three required top-level fields to `core/distribution.py`'s output (simplest — emit them as stubs matching the canonical snapshot shape).
- Fix option B: Update `test_every_snapshot_matches_canonical_schema` to skip `*.intelligence.json` files (they're a different schema family).
- Option B is safer — intelligence sidecars are NOT canonical snapshots and shouldn't be validated against the same schema.
- Also: add intelligence sidecar entries to `reports/index.json` (14 missing entries — `test_index_covers_all_real_snapshots_on_disk` failure).

**H2 — Create `data/snapshots/` directory**
- `data/adapters/rollup.py` calls `_latest_rollup_path()` which raises `FileNotFoundError` if the dir is absent.
- Fix: `mkdir -p data/snapshots && touch data/snapshots/.gitkeep && git add data/snapshots/.gitkeep`
- This unblocks `test_rollup_adapter_satisfies_contract_for_every_available_date`.

**H3 — Stability proof (20 trading days)**
- After H1+H2, need ~20 consecutive days of clean pipeline runs with no replay mismatches before P3b gate opens.
- Monitor: `python3 -m pytest tests/test_contracts.py` should stay green.
- The B1 bug (referenced in original HANDOFF_20260611.md but not fully defined) must also be resolved — check that doc for details.

---

### 🟡 P3b Activation (after Hardening signed off)

**B1 — Wire `momentum_direction`** (currently `"unknown"`)
- Source: `temporal_state.score_velocity`, `temporal_state.score_acceleration`
- Logic (in `core/ingest.py` → `_abstain_stock_record` or a new `_compute_momentum()`):
  ```python
  if velocity is None: return "unknown"
  if velocity > 0 and acceleration > 0: return "accelerating"
  if velocity > 0 and acceleration <= 0: return "decelerating"
  if velocity < 0: return "reversing"
  return "steady"
  ```
- Note: velocity/acceleration are abstained in P3a (`temporal_state.abstained.velocity = True`). This field only becomes meaningful when scoring activates.

**B2 — Wire `delta_vs_yesterday`** (currently `"—"`)
- Requires loading the prior day's snapshot during ingest to compare `composite_score` (or tier rank).
- `ingest()` already receives `prior_snapshots: dict[str, str]` (date → sha256) but NOT the actual snapshot content.
- Change: pass the prior day's stock records (or at least {ticker: composite_score}) as an optional param to `ingest()`.
- Output format: `"+3"` / `"-2"` / `"NEW"` (not in prior) / `"—"` (unchanged).

**B3 — Wire `signal_age_days`** (currently always `1`)
- Currently bootstrapped to 1 because `tier_in_current_state_days` is always 1 in P3a.
- When scoring activates and `tier` is non-IGNORE, the state machine will track real days-in-tier.
- No code change needed — just verify `temporal_state.tier_in_current_state_days` increments correctly once scoring is live.

---

### 🟢 Feature Backlog (from original HANDOFF_20260611.md)

**P3 — 雷達觀察頁「熱度分」(additive ranking layer)**
- Goal: display a relative heat score on the radar/watch page (NOT the golden layer).
- Tickers blocked by gates should still show heat score + reason tag (e.g. `❌ 超出成本上限 +18%`).
- Eliminates "why isn't X on the list" blind spots.
- Rule: must be display-only parallel layer; zero impact on `composite_score` / `tier` / `gates`.

**P4 — 板塊輪動強化**
- Schema already has `industry` field; aggregate net flow / W3 concentration by sector.
- Validates the financial stock (2887/2890/2884/2867/3033) W3 cluster finding from Session 2.
- Can be co-designed with P3.

**P5 — `weakening_profile` → daily snapshot**
- Move `weakening_profile` computation out of Streamlit render time and into the daily pipeline.
- Add `weakening` field to each stock record in the snapshot.
- Benefit: viewer no longer computes distribution detection for ~35 tickers on every render.

---

### 🔵 Operational / Infrastructure

**OPS-1 — Two-pipeline race mitigation**
- Root cause: local launchd + GitHub Actions both commit to `main` daily.
- Current workaround: manual `git pull --rebase` + conflict resolution.
- Proper fix: disable local launchd auto-push OR make local pipeline push to a `local/` branch and merge via PR. Alternatively, add a pipeline lock via a GHA environment or a `PIPELINE.lock` file in the repo.

**OPS-2 — TDCC refresh on non-Friday dates**
- `fetch_tdcc.py` is idempotent (skips if today's cache exists) but the pipeline calls it every day.
- Consider: only call on Fridays (or add a 7-day lag check) to avoid unnecessary HTTP hits.
- `config/scd.example.yaml` has `tdcc_max_lag_days: 7` — verify this is respected in `load_for_date()`.

---

## File Quick-Reference

| Purpose | File |
|---|---|
| Schema version constant | `core/ingest.py` → `SCHEMA_VERSION` |
| Completeness fields list | `core/ingest.py` → `_COMPLETENESS_FIELDS` |
| SKELETON gate | `core/golden.py` → `run()`, after `_tier_from_score()` |
| TDCC grade mapping | `data/adapters/tdcc_adapter.py` → `_LARGE_400_GRADES`, `_LARGE_1000_GRADE` |
| TDCC URL | `data/adapters/tdcc_adapter.py` → `TDCC_URL` |
| Adapter contract rules | `data/adapters/contract.py` |
| Index hash management | `reports/index.json` |
| Pipeline schedule (GHA) | `.github/workflows/daily.yml` |
| Config thresholds | `config/scd.example.yaml` |
