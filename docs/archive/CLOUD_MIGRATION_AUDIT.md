# Maitreya — Cloud Migration Compatibility Audit
**Phase 1 Report · Generated 2026-05-31**  
**Scope: GitHub Actions + Streamlit Community Cloud feasibility**  
**Status: Audit only — no code changed**

---

## Executive Summary

The migration is **feasible**. All primary data sources are public HTTP endpoints requiring no login, no cookies, and no browser. One source (WantGoo) is incompatible but already fails gracefully and is not in the main pipeline. The main work is not the fetchers — it is restructuring what gets committed to git.

---

## Phase 1 — Fetch Source Compatibility

### fetch_twse.py
```
Works in GitHub Actions?   ✅ YES
Reason:                    Official TWSE OpenAPI — CORS-enabled JSON, documented public API
Auth required?             No
Cookies required?          No
Rate limits?               Not documented; single call per day is negligible
IP restrictions?           No — openapi.twse.com.tw is open to all
Captcha?                   No
Notes:                     Rock solid. This is the most reliable source.
```

### fetch_fubon.py
```
Works in GitHub Actions?   ✅ YES (with low risk)
Reason:                    Plain HTTP GET of a public BIG5-encoded HTML page
                           No login, no session, no cookies in code
Auth required?             No
Cookies required?          No
Rate limits?               Not enforced at once-per-day cadence
IP restrictions?           Possible but unlikely — page is publicly browsable
Captcha?                   No
Notes:                     Two endpoints: ZGK_D (foreign) + ZGK_F (主力).
                           GitHub Actions IPs are well-known ranges; Fubon has
                           not historically blocked scrapers at this frequency.
                           Monitor first week for 403s.
```

### fetch_sinotrade.py
```
Works in GitHub Actions?   ✅ YES (with medium risk)
Reason:                    Plain HTTP GET, BIG5-encoded, docstring says "No auth required"
Auth required?             No
Cookies required?          No
Rate limits?               Medium risk — called once per ticker (~50–100 requests)
                           Requests are spread across tickers, not burst
IP restrictions?           Medium risk — stockchannelnew.sinotrade.com.tw could
                           block GitHub Actions IP ranges over time
Captcha?                   No
Notes:                     This is the highest-risk source. Not because of auth,
                           but because GitHub Actions uses a small pool of shared
                           IPs that are well-known. If Sinotrade adds IP blocking,
                           this breaks silently (returns empty HTML).
                           Mitigation: add a canary check in the workflow — if
                           branch count = 0 for known active tickers, flag it.
```

### fetch_tdcc.py
```
Works in GitHub Actions?   ✅ YES
Reason:                    Official TDCC opendata API with anonymous key
                           Downloads a single ~2.2MB CSV file
Auth required?             No — key=anonymous is public
Cookies required?          No
Rate limits?               Not documented; single download per day is fine
IP restrictions?           No — opendata.tdcc.com.tw is a government open data portal
Captcha?                   No
Notes:                     Weekly data (TDCC only updates weekly), so daily fetches
                           will often return the same data. That is fine — pipeline
                           handles it gracefully.
```

### fetch_market_pulse.py
```
Works in GitHub Actions?   ✅ YES
Reason:                    TWSE MI_INDEX + TAIFEX open data APIs
                           Both are official government financial APIs
Auth required?             No
Cookies required?          No
Rate limits?               No — official APIs
IP restrictions?           No
Captcha?                   No
Notes:                     Uses a standard browser User-Agent header which is
                           sufficient for both endpoints. No issues expected.
```

### fetch_wantgoo.py
```
Works in GitHub Actions?   ❌ NO
Reason:                    Anti-bot detection — returns 400 without fingerprint
                           headers; Chrome headless hangs on the page
Auth required?             Unknown (blocked before auth)
Cookies required?          Likely
Rate limits?               N/A — blocked at entry
IP restrictions?           Anti-bot blocks all automated access
Captcha?                   Likely (JS fingerprint challenge)
Notes:                     This source is ALREADY EXCLUDED from the main pipeline.
                           Code docstring explicitly states it fails gracefully.
                           fetch_daily.py does not call it. Non-issue.
```

### fetch_daily.py (orchestrator)
```
Works in GitHub Actions?   ✅ YES
Reason:                    Pure Python orchestrator — calls the above fetchers,
                           writes data/today.json. No external dependencies beyond
                           the fetchers listed above.
Notes:                     Path resolution uses __file__-relative paths which work
                           correctly in GitHub Actions checkout environment.
```

---

## Phase 1 Summary Table

| Source | GHA Compatible | Auth | Cookies | Risk Level | Blocker? |
|--------|---------------|------|---------|------------|----------|
| fetch_twse.py | ✅ YES | No | No | None | No |
| fetch_market_pulse.py | ✅ YES | No | No | None | No |
| fetch_tdcc.py | ✅ YES | No | No | None | No |
| fetch_fubon.py | ✅ YES | No | No | Low | No |
| fetch_sinotrade.py | ✅ YES | No | No | Medium | No (monitor) |
| fetch_wantgoo.py | ❌ NO | — | — | — | Already excluded |

**Verdict: All pipeline-critical sources are compatible. Migration is a go.**

---

## Phase 2 — Required Architectural Change (Critical)

This is the most important decision in the entire migration.

### The Problem
Currently `data/` and `reports/` are in `.gitignore`. The GitHub Actions workflow needs to:
1. Run fetch → ingest → archive
2. Commit the resulting files back to the repo
3. Have Streamlit Community Cloud read those files on next load

**This means `data/` and `reports/` must be versioned in git.**

### Decision Required

**Option A: Make the repo private, version all data**
- Set Maitreya repo to Private on GitHub
- Remove `data/` and `reports/` from `.gitignore`
- Commit snapshots, reports, index.json daily
- Streamlit Community Cloud can read directly from the repo

Pros: Simple, everything in one place  
Cons: Git history grows ~1–5MB per day; repo becomes large over time

**Option B: Keep repo public (code only), store data in a separate private repo**
- Keep Maitreya public (code + architecture)
- Create a second private repo `maitreya-data`
- GitHub Action writes to the data repo
- Streamlit reads from the data repo

Pros: Clean separation, public portfolio stays clean  
Cons: More complex setup, two repos to manage

**Recommendation: Option A with the repo set to Private.**  
This is a personal tool, not a public library. Private repo + versioned data is the simplest path. Git LFS is not needed at current data volumes.

---

## Phase 3 — .gitignore Changes Needed

Current `.gitignore` (too aggressive for cloud):
```
data/
reports/
```

Required `.gitignore` for cloud (keep code clean, version data):
```gitignore
# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/

# Personal documents
*.docx
*.xlsx
*.pdf

# Streamlit cache
.streamlit/

# macOS
.DS_Store

# Secrets (if any)
.env
secrets.json

# DO NOT ignore:
# data/          ← needed by GitHub Actions pipeline
# reports/       ← the intelligence archive, must be versioned
```

---

## Phase 4 — Streamlit Community Cloud Requirements

### What needs to exist in the repo root:
```
requirements.txt          ← Python dependencies
.streamlit/config.toml    ← optional, for theme settings
```

### Known dependency issues to check:
- `streamlit` version pin needed
- `plotly` version pin needed
- `pandas` version pin needed
- All `core/` imports must work from a clean clone with no local data

### Streamlit Community Cloud constraints:
- Free tier: 1 app, public or private repo
- Sleeps after ~7 days of inactivity (wakes on first visit, ~30s)
- 1GB RAM limit — should be fine for this app
- Reads directly from GitHub repo on each deploy/restart
- Does NOT have access to `data/` on your local Mac — repo must contain the data

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Sinotrade IP block | Low-Medium | Medium — branch data missing | Add canary check in workflow; alert on empty results |
| Fubon HTTP 403 | Low | Medium — foreign flow data missing | Same canary check |
| GitHub Actions cron drift | Low | Low — ±5min acceptable | Use `0 11 * * 1-5` (19:00 TWN) |
| TWSE API down | Very Low | Low — graceful fallback in code | Already handled |
| Streamlit sleep on inactivity | Certain | Low — 30s wake time | Acceptable for personal use |
| Git repo size growth | Certain | Low-Medium | ~1-3MB/day; manageable for 1-2 years |
| WORM integrity across git commits | Low | High | Verify sha256 files are committed alongside reports |

---

## Migration Plan (Phases 2–4)

**Prerequisites (do first):**
1. Set GitHub repo `Maitreya` to **Private**
2. Confirm you are okay with market data being stored in git history

**Phase 2 — GitHub Actions workflow**
- Create `.github/workflows/daily.yml`
- Schedule: `0 11 * * 1-5` (19:00 Taiwan = 11:00 UTC)
- Steps: checkout → setup Python → fetch → ingest → verify → commit → push

**Phase 3 — Update .gitignore**
- Remove `data/` and `reports/` from `.gitignore`
- Add back only cache/temp files
- Commit `data/` and `reports/` current state as baseline

**Phase 4 — Streamlit Community Cloud**
- Create `requirements.txt`
- Test clean-clone run locally
- Connect Community Cloud to GitHub repo
- Set entry point: `viewer/cockpit.py`

**Estimated work: 2–3 hours of setup, no logic changes.**

---

## What Does NOT Change

Per constraints — these are untouched:
- Scoring logic
- Funnel / state machine / golden / confidence
- Replay logic
- WORM archive logic
- All core/ modules
- All tests

The pipeline runs identically in GitHub Actions as it does on your Mac.
The only difference is where it runs and where the output files live.
