"""SCD Engine — internal temporal viewer.

Run from Ai stock/ via:
    streamlit run viewer/app.py
or:
    make viewer

Read-only. Replay-safe. No scoring. No AI generation.

Five panels:
  1. Snapshot Timeline       — dates, hashes, lookback, replay status
  2. Ticker History          — per-ticker state evolution across days
  3. Replay Integrity        — hash witnesses, provenance, archived raw refs
  4. Temporal Chain DAG      — visualize snapshot → prior dependency graph
  5. Observation Metrics     — continuity, streaks, transitions, events
"""
from __future__ import annotations

import pathlib
import sys

# Module-on-PYTHONPATH bootstrap (when run via `streamlit run viewer/app.py`,
# the entry script's dir is sys.path[0] which is viewer/, not Ai stock/).
_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from viewer import data as vd  # noqa: E402
from viewer import metrics as vm  # noqa: E402


# ===========================================================================
# Page config + header
# ===========================================================================

st.set_page_config(
    page_title="SCD Engine — Temporal Viewer",
    page_icon="⏱",
    layout="wide",
    initial_sidebar_state="expanded",
)


def render_header() -> None:
    cov = vm.coverage_summary()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Snapshots", cov["snapshot_count"])
    c2.metric("First date", cov["first_date"] or "—")
    c3.metric("Last date",  cov["last_date"] or "—")
    c4.metric("Span (days)", cov["calendar_span_days"])
    c5.metric("Weekday gaps", cov["weekday_gaps"])
    st.caption(
        "Read-only viewer. All scoring is currently abstained (P3a-Hardening). "
        "No writes happen here. Replay-safe."
    )


# ===========================================================================
# Panel 1 — Snapshot Timeline
# ===========================================================================

def panel_timeline() -> None:
    st.header("1 · Snapshot Timeline")
    st.caption("Every dated snapshot in `reports/index.json`. Click a row for replay-integrity detail below.")

    rows = [vm.snapshot_summary_row(d) for d in vd.real_dates()]
    if not rows:
        st.warning("No real-date snapshots found in `reports/`.")
        return

    df = pd.DataFrame(rows)
    df["current_hash_short"] = df["current_hash"].fillna("").str.slice(0, 20) + "…"
    show_cols = [
        "date", "universe_size", "lookback_depth", "history_revisions",
        "audit_event_count", "has_raw_archived", "has_worm_violation",
        "current_hash_short", "generated_at", "core_version",
    ]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    st.subheader("Per-snapshot replay status")
    statuses = [vd.integrity_status(d) for d in vd.real_dates()]
    sdf = pd.DataFrame([{
        "date":              s["date"],
        "sidecar_matches":   s["sidecar_matches"],
        "index_matches":     s["index_matches"],
        "all_three_agree":   s["all_three_agree"],
        "canonical_hash":    (s["canonical_hash"] or "")[:20] + "…",
    } for s in statuses])
    st.dataframe(sdf, use_container_width=True, hide_index=True)

    n_clean = sum(1 for s in statuses if s["all_three_agree"])
    if n_clean == len(statuses):
        st.success(f"All {n_clean}/{len(statuses)} snapshots: sidecar, index, and canonical re-hash agree.")
    else:
        st.error(f"{len(statuses) - n_clean} snapshot(s) failed three-witness integrity check.")


# ===========================================================================
# Panel 2 — Ticker History Viewer
# ===========================================================================

def panel_ticker_history() -> None:
    st.header("2 · Ticker History Viewer")
    st.caption("Walk a ticker's per-date state across the entire snapshot archive.")

    tickers = vd.all_tickers_across_history()
    if not tickers:
        st.warning("No tickers across any snapshot.")
        return

    default_idx = 0
    chosen = st.selectbox("Ticker", tickers, index=default_idx)

    history = vd.ticker_history(chosen)
    name_seen = next((r["name"] for r in history if r["name"]), None)
    st.markdown(f"### `{chosen}` · {name_seen or '—'}")

    # Streak summary
    streaks = next((r for r in vm.ticker_streaks() if r["ticker"] == chosen), None)
    if streaks:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Appearances", f"{streaks['appearances']}/{len(history)}")
        c2.metric("Coverage", f"{streaks['coverage_pct']}%")
        c3.metric("Current streak", streaks["current_streak"])
        c4.metric("Max streak", streaks["max_streak"])

    # State table
    state_df = pd.DataFrame([{
        "date":            r["date"],
        "present":         r["present"],
        "tier":            r["tier"],
        "score":           r["composite_score"],
        "current_price":   r["current_price"],
        "change_pct":      r["change_pct"],
        "volume":          r["volume"],
        "event_count":     len(r["audit_events"]),
    } for r in history])
    st.dataframe(state_df, use_container_width=True, hide_index=True)

    # ----- Ticker timeline charts -----
    st.subheader("Timeline charts")
    st.caption("Line charts plot the values from the state table above. Gaps appear where the ticker was absent.")
    chart_df = state_df.set_index("date")[["change_pct", "current_price", "volume"]].copy()
    # Convert to numeric, leaving NaN for None (Streamlit handles NaN as gaps).
    for col in chart_df.columns:
        chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce")
    series = st.radio(
        "Series",
        ["change_pct", "current_price", "volume", "all (separate charts)"],
        index=0, horizontal=True,
    )
    if series == "all (separate charts)":
        for col in ("change_pct", "current_price", "volume"):
            st.markdown(f"**{col}**")
            st.line_chart(chart_df[[col]], use_container_width=True, height=180)
    else:
        st.line_chart(chart_df[[series]], use_container_width=True, height=240)

    # Velocity / acceleration placeholders
    st.subheader("Temporal placeholders (P3a abstained)")
    st.caption(
        "Velocity and acceleration are not computed at P3a — `temporal_state.abstained` "
        "is `true` on every record. This panel will populate once P3b activates."
    )
    placeholder_df = pd.DataFrame([{
        "date":     r["date"],
        "present":  r["present"],
        "velocity": "abstained",
        "acceleration": "abstained",
    } for r in history])
    st.dataframe(placeholder_df, use_container_width=True, hide_index=True)

    # Audit trail for this ticker
    st.subheader("Audit events filtered by ticker")
    flat = []
    for r in history:
        for e in r["audit_events"]:
            flat.append({"date": r["date"], **{k: v for k, v in e.items() if k != "data"}})
    if flat:
        st.dataframe(pd.DataFrame(flat), use_container_width=True, hide_index=True)
    else:
        st.info(f"No per-ticker audit events recorded for `{chosen}` across {len(history)} dates.")


# ===========================================================================
# Panel 3 — Replay Integrity
# ===========================================================================

def panel_integrity() -> None:
    st.header("3 · Replay Integrity Panel")
    st.caption("Hash witnesses, provenance summary, and archived raw references for one date.")

    dates = vd.real_dates()
    if not dates:
        st.warning("No real-date snapshots.")
        return
    date = st.selectbox("Date", dates, index=len(dates) - 1)

    integ = vd.integrity_status(date)
    c1, c2, c3 = st.columns(3)
    c1.metric("Sidecar matches", "yes" if integ["sidecar_matches"] else "NO")
    c2.metric("Index matches",   "yes" if integ["index_matches"]   else "NO")
    c3.metric("All 3 agree",     "yes" if integ["all_three_agree"] else "NO")

    st.markdown("**Three-witness hashes**")
    hash_df = pd.DataFrame([
        {"witness": "canonical re-hash of file", "hash": integ["canonical_hash"]},
        {"witness": "sidecar (.sha256)",          "hash": integ["sidecar_hash"]},
        {"witness": "index.json current_hash",    "hash": integ["index_current_hash"]},
    ])
    st.dataframe(hash_df, use_container_width=True, hide_index=True)

    if not integ["all_three_agree"]:
        st.error(
            "Three-witness disagreement detected. Run `make verify-index` and "
            "`make verify-all-replay` to diagnose. Replay legitimacy is COMPROMISED for this date."
        )

    # Provenance + archive
    st.subheader("Provenance sources + archived raw")
    arch = vd.archived_raw_paths(date)
    if not arch:
        st.warning("Snapshot has no provenance sources (this should be impossible — contract violation).")
    else:
        prov_df = pd.DataFrame([{
            "source_id":       a["source_id"],
            "raw_file":        a["raw_file"],
            "raw_sha256":      (a["raw_sha256"]      or "")[:20] + "…" if a["raw_sha256"]      else None,
            "archived_sha256": (a["archived_sha256"] or "")[:20] + "…" if a["archived_sha256"] else None,
            "archived_copy_path": a["archived_copy_path"],
            "row_count":       a["row_count"],
            "fetched_at":      a["fetched_at"],
        } for a in arch])
        st.dataframe(prov_df, use_container_width=True, hide_index=True)

        all_match = all(
            a["raw_sha256"] == a["archived_sha256"]
            for a in arch
            if a["raw_sha256"] and a["archived_sha256"]
        )
        if all_match:
            st.success(
                f"All {len(arch)} archived source(s) cryptographically match their recorded raw_sha256."
            )
        else:
            st.error("Archive sha mismatch detected — WORM cryptographic proof broken.")

    # Audit log (full, for this date)
    with st.expander("Full audit log for this date", expanded=False):
        snap = vd.load_snapshot(date)
        audit_df = pd.DataFrame([{
            "event":  e.get("event"),
            "step":   e.get("step"),
            "ticker": e.get("ticker"),
            "reason": (e.get("reason") or "")[:120],
        } for e in snap.get("audit_log", [])])
        st.dataframe(audit_df, use_container_width=True, hide_index=True)


# ===========================================================================
# Panel 4 — Temporal Chain DAG
# ===========================================================================

def panel_chain() -> None:
    st.header("4 · Temporal Chain Visualization")
    st.caption(
        "Each node is one dated snapshot. Edges point from a snapshot to its lookback priors. "
        "Node fill encodes three-witness integrity status; the focus selector dims unrelated edges."
    )

    dates = vd.real_dates()
    if not dates:
        st.warning("No real-date snapshots.")
        return

    # ----- Controls -----
    c1, c2 = st.columns([2, 1])
    focus = c1.selectbox(
        "Focus date (bold + only show related edges)",
        ["(none)"] + dates,
        index=0,
        key="chain_focus",
    )
    rankdir = c2.radio("Orientation", ["LR", "TB"], horizontal=True, index=0)

    # Pre-compute integrity status for all dates so we can color nodes.
    integ_by_date = {d: vd.integrity_status(d) for d in dates}

    # Build reverse adjacency: who looks back at `d`?
    reverse: dict[str, list[str]] = {d: [] for d in dates}
    forward: dict[str, list[str]] = {}
    for d in dates:
        info = vm.lookback_chain_for(d)
        forward[d] = [e["date"] for e in info["lookback"]]
        for e in info["lookback"]:
            reverse.setdefault(e["date"], []).append(d)

    def _related_to(focus_date: str) -> set[str]:
        """Set of node names involved in any edge touching focus_date (BFS both ways)."""
        related = {focus_date}
        # walk forward (priors of priors)
        frontier = [focus_date]
        while frontier:
            nxt = []
            for n in frontier:
                for p in forward.get(n, []):
                    if p not in related:
                        related.add(p)
                        nxt.append(p)
            frontier = nxt
        # walk reverse (successors-of-successors)
        frontier = [focus_date]
        while frontier:
            nxt = []
            for n in frontier:
                for p in reverse.get(n, []):
                    if p not in related:
                        related.add(p)
                        nxt.append(p)
            frontier = nxt
        return related

    related: set[str] | None = None
    if focus != "(none)":
        related = _related_to(focus)

    # ----- Build DOT -----
    lines = [
        "digraph TemporalChain {",
        f"  rankdir={rankdir};",
        '  node [shape=box, fontname="Helvetica", style="rounded,filled"];',
    ]
    for d in dates:
        info = vm.lookback_chain_for(d)
        integ = integ_by_date[d]
        # Fill color by integrity: green = three witnesses agree; red = mismatch
        if integ["all_three_agree"]:
            fill = "#d4edda"  # soft green
        else:
            fill = "#f8d7da"  # soft red
        if info["bootstrap"]:
            border = ', color="#856404"'  # bootstrap border
        else:
            border = ""
        depth = len(info["lookback"])
        label_parts = [d, f"depth={depth}"]
        if info["bootstrap"]:
            label_parts.append("[BOOTSTRAP]")
        if not integ["all_three_agree"]:
            label_parts.append("[INTEGRITY!]")
        label = "\\n".join(label_parts)

        # Dim nodes not related to focus
        opacity = ""
        font_weight = ""
        penwidth = ""
        if related is not None:
            if d not in related:
                fill = "#f4f4f4"
                opacity = ', fontcolor="#aaaaaa"'
            if d == focus:
                penwidth = ", penwidth=3"
                font_weight = ""  # bold via penwidth instead

        lines.append(
            f'  "{d}" [label="{label}", fillcolor="{fill}"{border}{opacity}{penwidth}];'
        )

        for e in info["lookback"]:
            color = "#28a745" if e["matches_current"] else "#dc3545"
            edge_extra = ""
            if related is not None and (d not in related or e["date"] not in related):
                color = "#e8e8e8"
                edge_extra = ", style=dotted"
            lines.append(f'  "{d}" -> "{e["date"]}" [color="{color}"{edge_extra}];')

    lines.append("}")
    dot = "\n".join(lines)
    st.graphviz_chart(dot, use_container_width=True)

    st.caption(
        "**Node fill:** soft green = three-witness integrity OK · soft red = mismatch. "
        "**Edge color:** green = STRICT chain (lookback hash equals prior's current_hash) · "
        "red = LENIENT (hash exists in history but has been superseded). "
        "Yellow border = BOOTSTRAP."
    )

    # Per-date lookback table
    st.subheader("Detailed lookback per date")
    date = st.selectbox("Inspect date", dates, index=len(dates) - 1, key="chain_date")
    info = vm.lookback_chain_for(date)
    if info["bootstrap"]:
        st.info(f"`{date}` is a BOOTSTRAP_SNAPSHOT — no priors in lookback window.")
    else:
        lb_df = pd.DataFrame([{
            "prior_date":        e["date"],
            "hash":              e["hash"][:20] + "…",
            "matches_current":   e["matches_current"],
            "exists_in_index":   e["exists_in_index"],
            "index_current":     (e["index_current"] or "")[:20] + "…" if e["index_current"] else None,
        } for e in info["lookback"]])
        st.dataframe(lb_df, use_container_width=True, hide_index=True)

    # Reverse adjacency for the inspected date
    successors = sorted(reverse.get(date, []))
    if successors:
        st.caption(f"Snapshots that look back at `{date}`: {', '.join(successors)}")
    else:
        st.caption(f"No later snapshots reference `{date}` in their lookback window.")


# ===========================================================================
# Panel 5 — Observation Metrics
# ===========================================================================

def panel_metrics() -> None:
    st.header("5 · Observation-Only Metrics")
    st.caption("No trading signals. Continuity, streaks, transitions, and state evolution only.")

    # Continuity
    st.subheader("Calendar continuity")
    gaps = vm.calendar_gaps(weekends_ok=True)
    if not gaps:
        st.success("No weekday gaps — the chain is continuous over its observed range.")
    else:
        st.warning(f"{len(gaps)} weekday gap(s) detected (excluding weekends):")
        st.dataframe(pd.DataFrame(gaps), use_container_width=True, hide_index=True)

    # Streaks
    st.subheader("Per-ticker streaks across history")
    streaks = vm.ticker_streaks()
    if streaks:
        s_df = pd.DataFrame(streaks)
        st.dataframe(s_df, use_container_width=True, hide_index=True)
        st.caption(
            "Sorted by total appearances. `current_streak` = consecutive present days at the tail. "
            "`max_streak` = longest contiguous run anywhere in the window."
        )

    # Event counts (global)
    st.subheader("Audit event totals across all snapshots")
    ev = vm.global_event_summary()
    if ev:
        ev_df = pd.DataFrame(
            sorted(ev.items(), key=lambda x: -x[1]),
            columns=["event", "count"],
        )
        st.dataframe(ev_df, use_container_width=True, hide_index=True)

    # Event counts per date
    st.subheader("Audit event count per date")
    per_date = vm.audit_event_counts()
    if per_date:
        # Wide table: rows = date, cols = event types
        all_events = sorted({e for d in per_date.values() for e in d.keys()})
        rows = []
        for d in vd.real_dates():
            counts = per_date.get(d, {})
            rows.append({"date": d, **{e: counts.get(e, 0) for e in all_events}})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Lookback depth distribution
    st.subheader("Lookback depth distribution")
    dist = vm.lookback_depth_distribution()
    if dist:
        dist_df = pd.DataFrame(
            sorted(dist.items()), columns=["lookback_depth", "snapshot_count"]
        )
        st.dataframe(dist_df, use_container_width=True, hide_index=True)

    # Tier transitions
    st.subheader("Tier transitions (P3a: empty — all IGNORE)")
    trans = vm.tier_transitions()
    if not trans:
        st.info(
            "No tier transitions recorded. At P3a every record has `tier=IGNORE`. "
            "This panel will fill once P3b activates scoring."
        )
    else:
        st.dataframe(pd.DataFrame(trans), use_container_width=True, hide_index=True)


# ===========================================================================
# Panel 6 — Audit Explorer (cross-date)
# ===========================================================================

def panel_audit_explorer() -> None:
    st.header("6 · Audit Explorer")
    st.caption(
        "Browse audit events across every snapshot. Filter by event type, "
        "ticker substring, or step substring. Read-only — does not modify any file."
    )

    events = vm.all_audit_events_flat()
    if not events:
        st.warning("No audit events in any snapshot.")
        return

    # Filter controls
    all_event_types = sorted({e["event"] for e in events if e["event"]})
    all_dates = vd.real_dates()

    c1, c2, c3 = st.columns([2, 1, 1])
    selected_events = c1.multiselect(
        "Event types",
        all_event_types,
        default=all_event_types,
        key="audit_events",
    )
    date_range = c2.select_slider(
        "Date range",
        options=all_dates,
        value=(all_dates[0], all_dates[-1]) if len(all_dates) >= 2 else (all_dates[0], all_dates[0]),
        key="audit_date_range",
    )
    only_with_data = c3.checkbox("Only with `data` payload", value=False, key="audit_with_data")

    c4, c5 = st.columns(2)
    ticker_filter = c4.text_input("Ticker contains", value="", key="audit_ticker").strip()
    step_filter = c5.text_input("Step contains", value="", key="audit_step").strip()

    # Apply filters
    start, end = date_range
    filtered = [
        e for e in events
        if (e["event"] in selected_events)
        and (start <= e["date"] <= end)
        and (not only_with_data or e["has_data"])
        and (not ticker_filter or (e["ticker"] and ticker_filter in str(e["ticker"])))
        and (not step_filter or (e["step"] and step_filter in e["step"]))
    ]

    # Event-type tally for the filtered slice
    tally = {}
    for e in filtered:
        tally[e["event"]] = tally.get(e["event"], 0) + 1
    st.markdown(f"**{len(filtered):,} event(s)** match the current filter.")

    if tally:
        tally_df = pd.DataFrame(
            sorted(tally.items(), key=lambda x: -x[1]),
            columns=["event", "count"],
        )
        with st.expander("Event-type tally for current filter", expanded=False):
            st.dataframe(tally_df, use_container_width=True, hide_index=True)

    # Paginated table
    PAGE_SIZE = 200
    if len(filtered) > PAGE_SIZE:
        max_page = (len(filtered) - 1) // PAGE_SIZE + 1
        page = st.number_input(
            f"Page (1–{max_page}, {PAGE_SIZE} rows each)",
            min_value=1, max_value=max_page, value=1, step=1,
        )
        lo = (page - 1) * PAGE_SIZE
        hi = lo + PAGE_SIZE
        slice_ = filtered[lo:hi]
    else:
        slice_ = filtered

    if slice_:
        df = pd.DataFrame([{
            "date":      e["date"],
            "event":     e["event"],
            "ticker":    e["ticker"],
            "step":      e["step"],
            "node_path": e["node_path"],
            "data?":     "✓" if e["has_data"] else "",
            "reason":    e["reason"][:160] + ("…" if len(e["reason"]) > 160 else ""),
        } for e in slice_])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No events match the current filter.")


# ===========================================================================
# Panel 7 — Replay Status UI
# ===========================================================================

def panel_replay_status() -> None:
    st.header("7 · Replay Status")
    st.caption(
        "Three-witness integrity across the whole archive. This panel only "
        "READS files — it does not invoke the pipeline. For end-to-end "
        "verification (re-running ingest+archive) use `make verify-all-replay`."
    )

    summary = vm.integrity_summary_all()
    if not summary:
        st.warning("No real-date snapshots to verify.")
        return

    total = len(summary)
    clean = sum(1 for s in summary if s["all_three_agree"])
    sidecar_ok = sum(1 for s in summary if s["sidecar_matches"])
    index_ok = sum(1 for s in summary if s["index_matches"])

    if clean == total:
        st.success(
            f"✅ ALL CLEAN — {total}/{total} snapshots: sidecar, index, and canonical re-hash agree."
        )
    else:
        st.error(
            f"❌ {total - clean}/{total} snapshot(s) failed three-witness check. "
            "Run `make verify-index` for diagnostic detail."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total snapshots", total)
    c2.metric("Three-witness pass", f"{clean}/{total}")
    c3.metric("Sidecar matches",     f"{sidecar_ok}/{total}")
    c4.metric("Index matches",       f"{index_ok}/{total}")

    # Per-date grid
    st.subheader("Per-snapshot integrity")
    rows = []
    for s in summary:
        rows.append({
            "date":              s["date"],
            "three_witness":     "✅" if s["all_three_agree"] else "❌",
            "sidecar":           "match" if s["sidecar_matches"] else "MISMATCH",
            "index":             "match" if s["index_matches"]   else "MISMATCH",
            "canonical_hash":    (s["canonical_hash"] or "")[:20] + "…",
            "sidecar_hash":      (s["sidecar_hash"] or "")[:20] + "…",
            "index_hash":        (s["index_current_hash"] or "")[:20] + "…",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Drill-down on one date
    st.subheader("Drill down")
    dates = vd.real_dates()
    date = st.selectbox("Date", dates, index=len(dates) - 1, key="replay_status_date")
    s = vd.integrity_status(date)
    detail_df = pd.DataFrame([
        {"witness": "1. canonical re-hash of file",   "hash": s["canonical_hash"],
         "matches": True},
        {"witness": "2. sidecar (.sha256)",            "hash": s["sidecar_hash"],
         "matches": s["sidecar_matches"]},
        {"witness": "3. index.json current_hash",      "hash": s["index_current_hash"],
         "matches": s["index_matches"]},
    ])
    st.dataframe(detail_df, use_container_width=True, hide_index=True)

    # CLI-equivalent guidance
    with st.expander("CLI equivalents (run from `Ai stock/`)", expanded=False):
        st.code(
            "make verify-index            # three-witness pytest, same logic this panel runs\n"
            "make verify-all-replay       # stronger: re-run adapter + ingest + archive end-to-end\n"
            "make verify-replay DATE=2026-05-25  # one-date replay check",
            language="bash",
        )


# ===========================================================================
# Panel 8 — Daily Operations (per-date log of the scheduler)
# ===========================================================================

def panel_daily_ops() -> None:
    st.header("8 · Daily Operations")
    st.caption(
        "Surface of `tools/daily.py` runs from `reports/_daily_logs/<date>.log`. "
        "Each log is append-only — re-running the scheduler on the same date stacks records."
    )

    dates = vd.daily_log_dates()
    if not dates:
        st.info(
            "No daily logs found yet. The scheduler writes to "
            "`reports/_daily_logs/<date>.log` on every run — see `make daily-install` "
            "or run `make daily` manually."
        )
        return

    # Cross-date summary table
    rows = [vd.daily_log_summary_row(d) for d in dates]
    st.subheader("Per-date summary")
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    ok = sum(1 for r in rows if r["latest_status"] == "ok")
    fail = sum(1 for r in rows if r["latest_status"] and r["latest_status"] != "ok")
    c1, c2, c3 = st.columns(3)
    c1.metric("Logged dates", len(dates))
    c2.metric("Latest run ok",   ok)
    c3.metric("Latest run failed", fail)
    if fail == 0:
        st.success(f"Every logged date's most-recent run finished status=ok.")
    else:
        st.error(f"{fail} date(s) have a most-recent run that did NOT finish ok. Drill down below.")

    # Drill-down
    st.subheader("Drill into one date")
    date = st.selectbox("Date", dates, index=len(dates) - 1, key="daily_ops_date")
    runs = vd.daily_log_runs(date)

    if not runs:
        st.warning(f"No structured runs parsed from `{date}.log`.")
        return

    run_idx = st.number_input(
        f"Run (1 = oldest, {len(runs)} = latest)",
        min_value=1,
        max_value=len(runs),
        value=len(runs),
        step=1,
        key="daily_ops_run_idx",
    )
    run = runs[run_idx - 1]

    # Run-level summary
    start_rec = next((r for r in run if r.get("step") == "orchestrator_start"), None)
    end_rec = next((r for r in run if r.get("step") == "orchestrator_end"), None)
    c1, c2, c3 = st.columns(3)
    c1.metric("Started", (start_rec or {}).get("at", "—"))
    c2.metric("Ended",   (end_rec or {}).get("at",   "—"))
    final_status = (end_rec or {}).get("status", "no_end_record")
    c3.metric("Final status", final_status)

    if final_status == "ok":
        st.success(f"Run {run_idx}/{len(runs)} for `{date}` completed cleanly.")
    else:
        st.error(f"Run {run_idx}/{len(runs)} for `{date}` ended status={final_status}.")

    # Per-step table
    step_rows = []
    for r in run:
        step = r.get("step")
        if step in ("orchestrator_start", "orchestrator_end"):
            continue
        step_rows.append({
            "step":         step,
            "status":       r.get("status"),
            "returncode":   r.get("returncode"),
            "started_at":   r.get("started_at"),
            "finished_at":  r.get("finished_at"),
            "argv":         " ".join(r.get("argv", [])),
        })
    if step_rows:
        st.dataframe(pd.DataFrame(step_rows), use_container_width=True, hide_index=True)

    # Tail outputs expander
    with st.expander("stdout / stderr tails per step", expanded=False):
        for r in run:
            step = r.get("step")
            if step in ("orchestrator_start", "orchestrator_end"):
                continue
            st.markdown(f"**{step}** · rc={r.get('returncode')} · status={r.get('status')}")
            stdout_lines = r.get("stdout_tail", [])
            stderr_lines = r.get("stderr_tail", [])
            if stdout_lines:
                st.text("stdout:\n" + "\n".join(stdout_lines))
            if stderr_lines:
                st.text("stderr:\n" + "\n".join(stderr_lines))
            st.markdown("---")


# ===========================================================================
# Main
# ===========================================================================

PANELS = {
    "1 · Snapshot Timeline":    panel_timeline,
    "2 · Ticker History":       panel_ticker_history,
    "3 · Replay Integrity":     panel_integrity,
    "4 · Temporal Chain DAG":   panel_chain,
    "5 · Observation Metrics":  panel_metrics,
    "6 · Audit Explorer":       panel_audit_explorer,
    "7 · Replay Status":        panel_replay_status,
    "8 · Daily Operations":     panel_daily_ops,
}


def main() -> None:
    st.title("SCD Engine · Temporal Viewer")
    render_header()

    panel = st.sidebar.radio("Panels", list(PANELS.keys()), index=0)
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "**Phase:** P3a-Hardening (shipped)\n\n"
        "**Mode:** read-only, replay-safe\n\n"
        "**Scoring:** abstained — IGNORE on every record"
    )
    st.sidebar.markdown("---")
    if st.sidebar.button("Clear cache & reload"):
        st.cache_data.clear()
        st.rerun()

    PANELS[panel]()


if __name__ == "__main__":
    main()
