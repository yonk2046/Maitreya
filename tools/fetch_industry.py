"""Fetch TWSE/TPEx official industry codes → data/industry/industry_map.json.

Usage:
    python -m tools.fetch_industry            # fetch (skip if cache < 30 days)
    python -m tools.fetch_industry --force    # re-download regardless of age

Industry assignment changes rarely; the cache self-refreshes monthly.
Consumed by core/sector_intelligence.py for full-market sector mapping.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from data.adapters import industry_adapter
from data.adapters.legacy import _project_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch TWSE/TPEx industry classification")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()

    root = _project_root()
    industry_dir = root / "data" / "industry"

    age = industry_adapter.cache_age_days(industry_dir)
    if age is not None and not args.force and age < industry_adapter.MAX_AGE_DAYS:
        print(f"[fetch_industry] cache is {age:.1f}d old (< {industry_adapter.MAX_AGE_DAYS}d) — skip", file=sys.stderr)
        return

    print(f"[fetch_industry] downloading TWSE + TPEx industry codes …", file=sys.stderr)
    try:
        out = industry_adapter.fetch_and_save(industry_dir, force=args.force)
        print(f"[fetch_industry] ✅ saved → {out.relative_to(root)}", file=sys.stderr)
    except Exception as e:
        print(f"[fetch_industry] ❌ failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
