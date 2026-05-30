"""Internal temporal viewer for SCD Engine.

Read-only Streamlit application for debugging temporal logic, validating
continuity, and observing state evolution. Not a production frontend, not
a dashboard, not a SaaS interface — an internal observation tool.

Architectural constraints:
  - Read-only: never writes to reports/, index.json, raw data.
  - Replay-safe: invoking the viewer must not change canonical hashes.
  - No scoring: observation only, until P3b is signed off.
  - Local-only: bind to 127.0.0.1 by default.

Run via `make viewer` from the Ai stock/ directory.
"""
