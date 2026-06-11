"""Fetch TDCC 集保股權分散表 and cache to data/tdcc/<YYYYMMDD>.json.

Usage:
    python -m tools.fetch_tdcc            # fetch latest (skip if cached)
    python -m tools.fetch_tdcc --force    # re-download even if cached

TDCC publishes data every Friday after market close.
This script is called from fetch_daily.py on Fridays (or run manually).

Delegates all fetch/parse logic to data/adapters/tdcc_adapter.py.
Grade mapping (1 lot = 1,000 shares):
  large_holder_400_pct  = sum % of grades 12–15 (≥ 400 lots)
  large_holder_1000_pct = % of grade 15 only   (≥ 1000 lots)
  shareholder_count     = headcount from grade-17 total row
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from data.adapters import tdcc_adapter
from data.adapters.legacy import _project_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch TDCC weekly distribution data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()

    root     = _project_root()
    tdcc_dir = root / "data" / "tdcc"

    print(f"[fetch_tdcc] downloading from {tdcc_adapter.TDCC_URL} …", file=sys.stderr)
    try:
        out = tdcc_adapter.fetch_and_save(tdcc_dir, force=args.force)
        print(f"[fetch_tdcc] ✅ saved → {out.relative_to(root)}", file=sys.stderr)
    except Exception as e:
        print(f"[fetch_tdcc] ❌ failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
