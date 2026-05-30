# SCD Engine — P3a/P3a-Hardening pipeline entrypoints.
#
# All targets assume the working directory is "SCD engine/Ai stock/" and that
# the parent dir contains "data/" alongside this dir. If the resolver fails
# (e.g. Cowork sandbox dual-mount), set:
#     export SCD_PROJECT_ROOT="/path/to/SCD engine"
#
# Usage:
#     make help
#     make test                 # full pytest suite
#     make test-fast            # skip slow contract tests
#     make backfill DATE=2026-05-22
#     make backfill-all
#     make verify-replay DATE=2026-05-22
#     make fix-index            # idempotent supersedes-chain repair
#     make verify-index         # run integrity checks against reports/index.json
#     make clean-pycache

.PHONY: help test test-fast backfill backfill-all verify-replay verify-all-replay fix-index verify-index viewer cockpit cockpit-v2 restart-cockpit restart-cockpit-v2 streak-analyze transitions persistence-rank regime-monitor temporal-report market-flow narrative confidence golden golden-near-miss funnel state-machine intelligence intelligence-backfill daily daily-skip-fetch daily-install daily-uninstall daily-status daily-tail fetch fetch-dry-run fetch-pulse fetch-pulse-dry-run clean-pycache

PY ?= python3

help:
	@grep -E '^[a-zA-Z_-]+:.*?# ' $(MAKEFILE_LIST) \
	  | awk -F':.*# ' '{printf "  %-20s %s\n", $$1, $$2}'

test:  # run full pytest suite (replay + contracts + adapter + worm)
	$(PY) -m pytest tests/ -v

test-fast:  # quick run, no -v
	$(PY) -m pytest tests/ -q

backfill:  # ingest one date; DATE=YYYY-MM-DD required
	@[ -n "$(DATE)" ] || (echo "usage: make backfill DATE=YYYY-MM-DD" && exit 2)
	$(PY) -m tools.run_pipeline --date $(DATE) --source rollup

backfill-all:  # ingest every date available in data/snapshots rollup
	$(PY) -m tools.run_pipeline --backfill-all

verify-replay:  # re-run ingest and confirm canonical hash equality
	@[ -n "$(DATE)" ] || (echo "usage: make verify-replay DATE=YYYY-MM-DD" && exit 2)
	$(PY) -m tools.run_pipeline --date $(DATE) --check-replay

verify-all-replay:  # walk every indexed date and replay-check each
	$(PY) tools/verify_all_replay.py

viewer:  # launch the read-only Streamlit temporal viewer on :8501 (engineering panels)
	$(PY) -m streamlit run viewer/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false

cockpit:  # launch the bilingual market intelligence cockpit on :8502 (recommended)
	$(PY) -m streamlit run viewer/cockpit.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --browser.gatherUsageStats false

cockpit-v2:  # launch the v2 hierarchical intelligence cockpit on :8503
	$(PY) -m streamlit run viewer/cockpit_v2.py --server.address 127.0.0.1 --server.port 8503 --server.headless true --browser.gatherUsageStats false

restart-cockpit-v2:  # kill any running streamlit then relaunch cockpit-v2 on :8503
	-pkill -f "streamlit run" 2>/dev/null; sleep 1
	$(PY) -m streamlit run viewer/cockpit_v2.py --server.address 127.0.0.1 --server.port 8503 --server.headless true --browser.gatherUsageStats false

restart-cockpit:  # kill any running streamlit then relaunch cockpit on :8502
	-pkill -f "streamlit run" 2>/dev/null; sleep 1
	$(PY) -m streamlit run viewer/cockpit.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --browser.gatherUsageStats false

# ----- Temporal Observation Toolkit (read-only) -----

streak-analyze:  # per-ticker persistence rows across the snapshot archive
	$(PY) -m tools.temporal.streak_analyzer $(ARGS)

transitions:  # state/presence/sign transitions across consecutive snapshots
	$(PY) -m tools.temporal.transition_detector $(ARGS)

persistence-rank:  # rank tickers by temporal persistence (modes: coverage|stability|tail_run|composite)
	$(PY) -m tools.temporal.persistence_ranker $(ARGS)

regime-monitor:  # market-wide descriptive observations per snapshot
	$(PY) -m tools.temporal.regime_monitor $(ARGS)

market-flow:  # P3c: market regime + capital flow + leadership rotation across all dates
	$(PY) -m tools.temporal.market_flow_monitor $(ARGS)

narrative:  # P3c-Narrative: bilingual market intelligence from temporal metrics
	$(PY) -m core.narrative_engine $(ARGS)

confidence:  # P3g: confidence & risk profile — 2D per-ticker reading + market temperature
	$(PY) -m core.confidence $(ARGS)

golden:  # P3f: golden layer v2 — high-conviction watchlist (prime/strong/qualified)
	$(PY) -m core.golden $(ARGS)

golden-near-miss:  # P3f: golden layer v2 — include near-miss entries
	$(PY) -m core.golden --near-miss $(ARGS)

intelligence:  # P3h: generate daily intelligence report → reports/YYYY-MM-DD.intelligence.json
	@if [ -n "$(DATE)" ]; then \
	  $(PY) -m core.intelligence_delta --date $(DATE) $(ARGS); \
	else \
	  $(PY) -m core.intelligence_delta $(ARGS); \
	fi

intelligence-backfill:  # P3h: generate intelligence reports for all dates missing one
	$(PY) -m core.intelligence_delta --backfill $(ARGS)

funnel:  # P3e: candidate funnel engine — discovery through failure layers
	$(PY) -m core.funnel $(ARGS)

state-machine:  # P3e: temporal state machine — lifecycle states for all tickers
	$(PY) -m core.state_machine $(ARGS)

market-state:  # P3d: unified market state engine (condition + flow + leadership + narrative)
	$(PY) -m core.market_state $(ARGS)

market-state-json:  # P3d: full market state as JSON
	$(PY) -m core.market_state --json $(ARGS)

market-state-flow:  # P3d: capital flow summary only
	$(PY) -m core.market_state --layer flow $(ARGS)

temporal-report:  # run all four toolkit views in sequence
	@echo "===== STREAK ANALYZER =====" && $(PY) -m tools.temporal.streak_analyzer
	@echo "" && echo "===== TRANSITIONS =====" && $(PY) -m tools.temporal.transition_detector
	@echo "" && echo "===== PERSISTENCE RANK (composite) =====" && $(PY) -m tools.temporal.persistence_ranker --mode composite
	@echo "" && echo "===== REGIME MONITOR =====" && $(PY) -m tools.temporal.regime_monitor

# ----- Daily auto-ingest scheduler -----

daily:  # run the full daily flow once: fetch -> ingest+archive -> verify-all-replay
	$(PY) -m tools.daily

daily-skip-fetch:  # same, but use the existing data/today.json instead of refetching
	$(PY) -m tools.daily --skip-fetch

daily-install:  # macOS only — install ~/Library/LaunchAgents/com.scd.daily.plist (weekdays 19:00)
	bash deploy/install_launchd.sh install

daily-uninstall:  # macOS only — remove the launchd job
	bash deploy/install_launchd.sh uninstall

daily-status:  # show launchd installation/load status
	bash deploy/install_launchd.sh status

daily-tail:  # tail today's daily log (or pass DATE=YYYY-MM-DD)
	@d=$${DATE:-$$(date +%Y-%m-%d)}; \
	  f="reports/_daily_logs/$$d.log"; \
	  if [ -f "$$f" ]; then echo "==> $$f"; cat "$$f" | $(PY) -c "import sys,json; [print(json.dumps(json.loads(l), indent=2, ensure_ascii=False)) for l in sys.stdin if l.strip()]"; \
	  else echo "no log at $$f"; fi

fetch:  # run upstream fetch only (fubon+twse+sinotrade) → writes data/today.json + data/branches/
	cd .. && $(PY) tools/fetch_daily.py

fetch-dry-run:  # dry-run fetch (prints plan, no writes)
	cd .. && $(PY) tools/fetch_daily.py --dry-run

fetch-pulse:  # fetch TAIEX + TX futures + 三大法人台指期未平倉 → data/market_pulse.json
	cd .. && $(PY) tools/fetch_market_pulse.py

fetch-pulse-dry-run:  # dry-run market pulse fetch (prints, no writes)
	cd .. && $(PY) tools/fetch_market_pulse.py --dry-run

fix-index:  # idempotent: link supersedes chain in reports/index.json
	$(PY) tools/fix_index_supersedes.py

verify-index:  # integrity scan over reports/index.json (no writes)
	$(PY) -m pytest tests/test_contracts.py -v

clean-pycache:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
