"""
SCD Engine — Factor Correlation Analyzer (observability only)

Reads N historical snapshots, extracts leaf raw_inputs (from score_tree),
computes Pearson / Spearman / mutual-information correlations, emits report.

This tool is OBSERVATIONAL. It does not modify scoring rules or factor weights.
See docs/CORRELATION_REPORT.md for usage philosophy.

Usage:
    python -m tools.correlation_analyzer \\
        --snapshots reports/2026-*.json \\
        --leaves chip.fii.sync_score,chip.fii.ratio_score,... \\
        --output reports/correlation_2026-Q2

Requires:
    pip install pandas scipy scikit-learn jinja2
"""

from __future__ import annotations
import argparse
import json
import pathlib
import sys
from decimal import Decimal
from typing import Iterable

# Lazy imports so the file is parseable without deps installed
def _need(mod_name):
    try:
        return __import__(mod_name)
    except ImportError:
        sys.stderr.write(f"missing dependency: {mod_name}; install with `pip install {mod_name}`\n")
        sys.exit(1)


SCHEMA_LEAVES_ALL = [
    # chip
    "composite.chip_score.fii_sub.sync_score",
    "composite.chip_score.fii_sub.ratio_score",
    "composite.chip_score.fii_sub.trend_score",
    "composite.chip_score.mainforce_sub.days_score",
    "composite.chip_score.mainforce_sub.lock_score",
    "composite.chip_score.mainforce_sub.streak_score",
    "composite.chip_score.mainforce_sub.concentration_score",
    # behavior
    "composite.behavior_score.concentration_sub.shareholders_score",
    "composite.behavior_score.concentration_sub.diff_score",
    "composite.behavior_score.concentration_sub.L400_score",
    "composite.behavior_score.concentration_sub.L1000_score",
    "composite.behavior_score.margin_sub.maintenance_score",
    "composite.behavior_score.margin_sub.wash_score",
    "composite.behavior_score.margin_sub.penalty_score",
    # structure
    "composite.structure_score.price_action_score",
    "composite.structure_score.trend_2h_score",
]


def walk_tree(node: dict, path: str = "composite"):
    """Yield (path, node) for every node in the score_tree."""
    yield path, node
    if node.get("kind") == "internal" and "inputs" in node:
        for name, child in node["inputs"].items():
            yield from walk_tree(child, f"{path}.{name}")


def extract_row(snapshot: dict, leaf_paths: list[str]) -> list[dict]:
    """Return one dict per (ticker, leaf_path) with raw_inputs spread out."""
    date = snapshot["date"]
    rows = []
    for stock in snapshot.get("stocks", []):
        st = stock.get("score_tree")
        if not st: continue
        ticker = stock["ticker"]
        nodes_by_path = dict(walk_tree(st["root"]))
        row = {"ticker": ticker, "date": date}
        for lp in leaf_paths:
            node = nodes_by_path.get(lp)
            if node is None or node.get("abstained"):
                row[lp] = None
            else:
                # Use the leaf raw input(s); if multiple, take first or concat
                ri = node.get("raw_inputs") or {}
                if len(ri) == 1:
                    row[lp] = list(ri.values())[0]
                else:
                    # multi-input leaf: store dict; user can extract specific keys
                    row[lp] = ri
        rows.append(row)
    return rows


def compute_correlations(df, leaf_paths: list[str]):
    """Return three DataFrames: pearson, spearman, mutual_info."""
    pd = _need("pandas")
    scipy_stats = _need("scipy.stats") if False else __import__("scipy.stats", fromlist=["stats"])
    from sklearn.feature_selection import mutual_info_regression

    n_leaves = len(leaf_paths)
    pearson  = pd.DataFrame(index=leaf_paths, columns=leaf_paths, dtype=float)
    spearman = pd.DataFrame(index=leaf_paths, columns=leaf_paths, dtype=float)
    mi       = pd.DataFrame(index=leaf_paths, columns=leaf_paths, dtype=float)
    counts   = pd.DataFrame(index=leaf_paths, columns=leaf_paths, dtype=int)

    for i, a in enumerate(leaf_paths):
        for j, b in enumerate(leaf_paths):
            sub = df[[a, b]].dropna()
            if len(sub) < 20:
                pearson.loc[a,b] = float("nan")
                spearman.loc[a,b] = float("nan")
                mi.loc[a,b] = float("nan")
                counts.loc[a,b] = len(sub)
                continue
            try:
                pearson.loc[a,b],  _ = scipy_stats.pearsonr (sub[a], sub[b])
                spearman.loc[a,b], _ = scipy_stats.spearmanr(sub[a], sub[b])
            except Exception:
                pearson.loc[a,b]  = float("nan")
                spearman.loc[a,b] = float("nan")
            if i != j:
                try:
                    mi.loc[a,b] = float(mutual_info_regression(sub[[a]], sub[b], random_state=0)[0])
                except Exception:
                    mi.loc[a,b] = float("nan")
            else:
                mi.loc[a,b] = float("nan")
            counts.loc[a,b] = len(sub)
    return pearson, spearman, mi, counts


def emit_markdown_report(pearson, spearman, mi, counts, out_path: pathlib.Path):
    """Write a Markdown summary highlighting |r|>0.5 pairs."""
    lines = ["# Factor Correlation Report (auto-generated)", ""]
    lines.append(f"- Leaves analyzed: {len(pearson)}")
    lines.append(f"- Min pair sample size: {counts.values.min()}")
    lines.append("")
    lines.append("## Pairs with |Pearson r| ≥ 0.5 (excluding diagonal)")
    lines.append("")
    lines.append("| Leaf A | Leaf B | Pearson r | Spearman ρ | MI | n |")
    lines.append("|---|---|---|---|---|---|")
    pairs = []
    for a in pearson.index:
        for b in pearson.columns:
            if a >= b: continue   # avoid dup
            r = pearson.loc[a,b]
            if r is None or (isinstance(r, float) and (r != r)): continue
            if abs(r) >= 0.5:
                pairs.append((abs(r), a, b, r, spearman.loc[a,b], mi.loc[a,b], counts.loc[a,b]))
    pairs.sort(reverse=True)
    for _, a, b, r, s, m, n in pairs:
        lines.append(f"| `{a}` | `{b}` | {r:+.3f} | {s:+.3f} | {m:.3f} | {n} |")
    if not pairs:
        lines.append("| _(none)_ | | | | | |")
    lines.append("")
    lines.append("Interpretation rules (see docs/CORRELATION_REPORT.md §2.4):")
    lines.append("- |r| > 0.7  → suspect redundancy; require P4 IC test before removal")
    lines.append("- 0.5 < |r| ≤ 0.7 → moderate overlap; consider orthogonalization in P4")
    lines.append("- |r| ≤ 0.5 → independent")
    out_path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", nargs="+", required=True,
                    help="glob patterns or paths to snapshot JSON files")
    ap.add_argument("--leaves", default=",".join(SCHEMA_LEAVES_ALL),
                    help="comma-sep list of leaf paths to include (default: all)")
    ap.add_argument("--output", required=True, help="output prefix (will write .md / .json / .html)")
    ap.add_argument("--min-rows", type=int, default=60, help="warn if pair sample < this")
    args = ap.parse_args()

    pd = _need("pandas")

    paths: list[pathlib.Path] = []
    for pattern in args.snapshots:
        paths.extend(sorted(pathlib.Path().glob(pattern)))
    if not paths:
        sys.exit("no snapshots matched")

    leaf_paths = args.leaves.split(",")
    all_rows = []
    for p in paths:
        snap = json.loads(p.read_text())
        all_rows.extend(extract_row(snap, leaf_paths))
    if not all_rows:
        sys.exit("no rows extracted; do snapshots contain score_tree?")

    df = pd.DataFrame(all_rows)
    print(f"loaded {len(df)} ticker-day rows from {len(paths)} snapshots", file=sys.stderr)

    pearson, spearman, mi, counts = compute_correlations(df, leaf_paths)
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    # markdown
    emit_markdown_report(pearson, spearman, mi, counts, out.with_suffix(".md"))
    # machine-readable
    out.with_suffix(".json").write_text(json.dumps({
        "pearson":  pearson.to_dict(),
        "spearman": spearman.to_dict(),
        "mutual_info": mi.to_dict(),
        "counts":   counts.to_dict()
    }, indent=2))
    print(f"wrote {out.with_suffix('.md')} and {out.with_suffix('.json')}", file=sys.stderr)


if __name__ == "__main__":
    main()
