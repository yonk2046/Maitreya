"""Data adapters — read external sources into canonical raw_inputs.

Each adapter is a pure function:
    adapter(date, paths) -> (raw_inputs: dict, provenance_source: dict, audit_events: list)

Adapters MUST be deterministic given the same input files.
"""
