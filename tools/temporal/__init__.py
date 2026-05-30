"""Temporal Observation Toolkit (P3a-Visibility).

Strictly observational, read-only, replay-safe analytics over the
historical snapshot archive. NO scoring activation, NO prediction, NO
ranking tuning, NO AI-generated recommendations.

Modules:
  _loader.py            — read-only snapshot loaders (no streamlit dep)
  temporal_metrics.py   — pure metric primitives (velocity, persistence, ...)
  streak_analyzer.py    — per-ticker persistence rows
  transition_detector.py — state/presence/rank transitions
  persistence_ranker.py — rank by temporal stability, not score
  regime_monitor.py     — market-wide descriptive observations

Every CLI is importable AND runnable as `python -m tools.temporal.<name>`.
"""
