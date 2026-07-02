# Contributing to SCD Engine

> Status as of 2026-07-02: **P3b unlocked**（Yonki 2026-06-24 簽核）— scoring
> work and new snapshot fields are allowed; changing *existing* snapshot
> fields still requires a schema bump + replay safety. Current phase state
> lives in the latest `MAITREYA_HANDOFF_*.md`. Read
> [docs/REPLAY.md](docs/REPLAY.md) first if you haven't.

## Project layout & path quirk

The project layout assumes two sibling directories under a single parent:

```
SCD engine/
├── Ai stock/                 # canonical code lives here (this repo)
│   ├── core/                 # ingest / hashing / archive / worm_check
│   ├── data/adapters/        # legacy + rollup + contract
│   ├── reports/              # immutable snapshot output
│   │   ├── <date>.json + .sha256
│   │   ├── _raw_archive/<date>/   # archived raw inputs
│   │   └── index.json
│   ├── schema/canonical_schema.json
│   ├── tools/run_pipeline.py
│   └── tests/
└── data/                     # the actual raw inputs the adapters read
    ├── today.json            # live feed
    ├── branches/*.json       # branch-level data per ticker
    ├── snapshots/*.json      # historical multi-day rollups
    └── history/              # optional long history
```

The adapter's `_project_root()` walks up from `data/adapters/legacy.py`
looking for a parent that contains both `Ai stock` and `data` as direct
children. On a normal local checkout this resolves to `SCD engine/`.

### Dual-mount environments (Cowork sandbox, CI containers)

If `Ai stock/` and `data/` are mounted as separate top-level directories
that **don't share a parent in the VM filesystem**, the parent walk will
fail. Three escape hatches in priority order:

1. **`SCD_PROJECT_ROOT` env var** — set it to the absolute path of the
   dir that contains both `Ai stock` and `data` siblings:
   ```bash
   export SCD_PROJECT_ROOT="/path/to/SCD engine"
   make test
   ```
   This wins over all other lookup methods.

2. **Run from inside `SCD engine/Ai stock/`** — if both `Ai stock` and
   `data` exist as children of a directory you can `cd` into, the
   parent-walk fallback finds them automatically.

3. **`SCD engine` peer-dir fallback** — if a sibling dir literally named
   `SCD engine` exists at any ancestor level, it's used. Set up by the
   resolver for the specific dual-mount layout in Cowork.

If none resolve, `_project_root()` raises `RuntimeError` with a hint.

## Day-to-day workflow

```bash
# from Ai stock/
make help              # show all targets
make test              # full pytest suite (replay + contracts + adapter + worm)
make test-fast         # quiet pytest

make backfill DATE=2026-05-22         # one date from data/snapshots rollup
make verify-replay DATE=2026-05-22    # re-run and confirm canonical hash match
make backfill-all                     # iterate every date in rollup

make fix-index                        # idempotent supersedes-chain repair
make verify-index                     # contracts test only (no write)
```

## What runs on every ingest

1. **WORM manifest capture** (`core/worm_check.py`) — snapshot SHA-256 of
   every file under `data/today.json`, `data/branches/`, `data/snapshots/`,
   `data/history/`.
2. **Adapter** (`data/adapters/legacy.py` or `rollup.py`) — reads raw
   inputs, emits `AdapterOutput` validated by `data/adapters/contract.py`
   before returning. Contract violation → adapter raises.
3. **Ingest** (`core/ingest.py`) — builds v1.4 canonical snapshot with all
   scoring abstained (`tier="IGNORE"`, `composite_score=0`). Emits
   `BOOTSTRAP_SNAPSHOT` or `LOOKBACK_VERIFIED` based on prior snapshots.
4. **Raw archive** (`core/archive.py`) — copies every referenced raw
   file/dir into `reports/_raw_archive/<date>/<source_id>/`, re-hashes,
   confirms archive sha == raw_sha. Mutates snapshot to add
   `archived_copy_path` + `archived_sha256` per source and emits
   `RAW_ARCHIVED`.
5. **WORM verify** (`core/worm_check.py`) — re-snapshots manifest and
   compares. Any drift → emits `WORM_VIOLATION` and **aborts pipeline
   before writing**. The snapshot is never persisted if WORM is violated.
6. **Write** — pretty-print JSON to `reports/<date>.json`, write
   canonical-hash sidecar `<date>.json.sha256`, update `reports/index.json`
   (linking the supersedes chain if the hash changed from prior current).
7. **Optional**: `--check-replay` re-runs ingest end-to-end and verifies
   the two canonical hashes match (after normalizing `generated_at`).

## Contracts you MUST NOT break in P3a-Hardening

- **Replay determinism**: `canonical_sha256(snapshot)` is byte-stable
  given identical inputs. `generated_at` is the only allowed wall-clock
  field and is excluded from replay match by test convention.
- **WORM**: `data/` is read-only at runtime. Any code that writes under
  `data/` is a defect and will trip `WORM_VIOLATION`.
- **Schema**: every snapshot in `reports/` must validate against
  `schema/canonical_schema.json`. `audit_log[].event` enum is enforced.
- **Adapter contract**: every adapter must call `validate_adapter_output()`
  before returning. New raw_input keys need contract update first.
- **Index integrity**: `index.json` is append-only. Every `current_hash`
  must equal the canonical hash recomputed from the file on disk. The
  supersedes chain links every history entry forward and backward.

## Scoring status（updated 2026-07-02）

The old "scoring GATED / tier must stay IGNORE" rule was lifted on
2026-06-24 (P3b sign-off). `core/golden.py` computes real
prime/strong/qualified tiers live (viewer + backtest); ingest still writes
abstained values (`tier="IGNORE"`, `composite_score=0`) — writing real
scores back into snapshots is an optional formal step that requires a
schema bump. See the latest `MAITREYA_HANDOFF_*.md` before touching this.

## Adding a new audit event

1. Add the event name to `schema/canonical_schema.json` `audit_log[].event` enum.
2. Add a row to the table in `docs/AUDIT_LOG_EVENTS.md` §1.
3. Add a per-event spec section in §4 with: when emitted, typical reason
   string, payload `data` shape, severity.
4. Run `make test` — `test_every_snapshot_matches_canonical_schema` will
   catch any snapshot using the event before schema acknowledged it.

## Adding a new adapter

1. Implement `adapt_<name>()` returning the shape defined in
   `data/adapters/contract.py` (`_REQUIRED_TOP_KEYS`).
2. Call `validate_adapter_output(out, adapter_name="<name>.adapt_<name>")`
   as the last line before `return`.
3. Add a test to `tests/test_adapter_contract.py` that runs the new
   adapter against real or canned data and confirms the contract holds.
4. If the adapter introduces new raw_input keys ingest expects, update
   `_REQUIRED_RAW_KEYS` in `contract.py` first.

## Updating raw inputs

Don't. The pipeline assumes WORM. If you genuinely need to update raw
inputs (e.g., upstream fixed a corrupted feed):

1. Save the new raw file with a new name OR bump its mtime deliberately.
2. Re-run `make backfill DATE=...` — this writes a NEW snapshot with a
   different `canonical_sha256`, which auto-links into the supersedes
   chain (old hash gets `superseded_by`, new hash becomes `current`).
3. Both snapshots remain on disk and in the history; nothing is ever
   deleted. The audit trail tells the reproducer which raw version was
   in effect at each point.
