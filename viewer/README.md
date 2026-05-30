# SCD Engine · Temporal Viewer

> **Internal debugging tool.** Not a product. Not a dashboard. Not a SaaS UI.
> A read-only window into the temporal engine so you can reason about the
> system visually instead of grepping JSON.

## What it is

A single-page Streamlit app with five panels, all read-only:

1. **Snapshot Timeline** — every dated snapshot, its hash, lookback depth,
   audit-event count, and three-witness replay status (sidecar vs. index
   vs. on-the-fly canonical re-hash).
2. **Ticker History Viewer** — pick a ticker, see its per-date state across
   the entire snapshot archive, current/max streaks, velocity/acceleration
   placeholders (currently abstained at P3a), and per-ticker audit trail.
3. **Replay Integrity Panel** — for one date: three-witness hash check,
   provenance source table with `archived_copy_path` + `archived_sha256`,
   full audit log.
4. **Temporal Chain DAG** — Graphviz visualization of every snapshot and
   the edges to its lookback priors. Green edge = lookback hash equals
   prior's current_hash (STRICT chain). Red = points at a now-superseded
   hash (LENIENT — still in history).
5. **Observation-Only Metrics** — calendar continuity gaps, per-ticker
   streaks, audit event totals, lookback depth distribution, tier
   transitions (empty at P3a — wired for P3b).

## Architecture constraints

- **Read-only.** The viewer never writes to `reports/`, `index.json`, raw
  inputs, or anywhere else. It only reads + recomputes hashes.
- **Replay-safe.** Running the viewer must not alter any canonical hash.
  Verified by `tests/test_viewer_data.py`.
- **No scoring.** The Tier Transitions panel exists structurally but is
  empty at P3a because every record is `tier=IGNORE`. Velocity and
  acceleration columns show `abstained` until P3b.
- **No AI generation.** This is purely a deterministic projection of the
  data on disk.
- **Local-only.** `make viewer` binds to `127.0.0.1` and disables
  Streamlit telemetry.

## How to run

```bash
# from Ai stock/
make viewer
# → opens http://localhost:8501
```

Cache: hashes and JSON loads are cached by file mtime+size. Use the
sidebar **Clear cache & reload** button if you've just re-ingested a
snapshot and want the viewer to pick up the change immediately.

## Module layout

```
viewer/
├── __init__.py        — module docstring + constraints reminder
├── app.py             — Streamlit entry point with five panels
├── data.py            — cached read-only loaders (uses core.hashing)
├── metrics.py         — observation-only temporal metrics (pure funcs)
└── README.md          — this file
```

## What this isn't

- Not a place to add scoring logic. Scoring lives in `core/` (gated until P3b).
- Not a place to add API endpoints. This is for human eyes only.
- Not a long-running service. It's `streamlit run`, killable, ephemeral.
- Not a frontend codebase. No React, no TypeScript, no build step.

When P3b activates and scoring becomes live, the existing panels light up
automatically — the columns and event types are already wired through.
