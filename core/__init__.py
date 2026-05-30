"""SCD Engine core — deterministic market state engine.

Public API:
    hashing.canonical_bytes(obj) -> bytes
    hashing.canonical_sha256(obj) -> str ("sha256:<hex>")
    ingest.ingest(raw_inputs, config, prior_snapshots=None) -> Snapshot dict
"""

__version__ = "0.1.0-p3a"
