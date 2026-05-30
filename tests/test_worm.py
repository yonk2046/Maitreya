"""WORM (Write-Once-Read-Many) self-check tests.

Validates `core.worm_check`:
  - Clean run: manifest before == manifest after, no violations.
  - Tampered run: mutating a file under data/ between snapshots produces a
    WORM_VIOLATION event with before/after hashes.
  - Removed file: a deletion produces a WORM_VIOLATION.
  - Added file: a new file produces a WORM_VIOLATION.

Uses tmp_path so we never touch the real data/ tree.

Run:
    cd "Ai stock" && python -m pytest tests/test_worm.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.worm_check import snapshot_manifest, verify_manifest  # noqa: E402


@pytest.fixture
def fake_project(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a minimal fake project root with data/today.json + a few branches/snapshots."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "today.json").write_text('{"tradingDate":"2026-05-25"}', encoding="utf-8")

    branches = tmp_path / "data" / "branches"
    branches.mkdir()
    (branches / "2330.json").write_text('{"buyBranches":[]}', encoding="utf-8")
    (branches / "2454.json").write_text('{"buyBranches":[]}', encoding="utf-8")

    snaps = tmp_path / "data" / "snapshots"
    snaps.mkdir()
    (snaps / "rollup_2026-05.json").write_text('{"days":{}}', encoding="utf-8")
    return tmp_path


def test_clean_run_no_violations(fake_project):
    before = snapshot_manifest(fake_project)
    assert len(before) == 4  # today + 2 branches + 1 rollup
    violations = verify_manifest(fake_project, before)
    assert violations == []


def test_modification_emits_violation(fake_project):
    before = snapshot_manifest(fake_project)
    # Tamper: rewrite branches/2330.json with different content
    (fake_project / "data" / "branches" / "2330.json").write_text(
        '{"buyBranches":[{"broker":"凱基-台北"}]}', encoding="utf-8"
    )
    violations = verify_manifest(fake_project, before)
    assert len(violations) == 1
    v = violations[0]
    assert v["event"] == "WORM_VIOLATION"
    assert "modified during ingest" in v["reason"]
    assert v["data"]["path"] == "data/branches/2330.json"
    assert v["data"]["before"] != v["data"]["after"]
    assert v["data"]["before"].startswith("sha256:")
    assert v["data"]["after"].startswith("sha256:")


def test_removal_emits_violation(fake_project):
    before = snapshot_manifest(fake_project)
    (fake_project / "data" / "branches" / "2454.json").unlink()
    violations = verify_manifest(fake_project, before)
    assert len(violations) == 1
    v = violations[0]
    assert v["event"] == "WORM_VIOLATION"
    assert "removed during ingest" in v["reason"]
    assert v["data"]["after"] is None


def test_addition_emits_violation(fake_project):
    before = snapshot_manifest(fake_project)
    (fake_project / "data" / "branches" / "9999.json").write_text(
        '{"buyBranches":[]}', encoding="utf-8"
    )
    violations = verify_manifest(fake_project, before)
    assert len(violations) == 1
    v = violations[0]
    assert v["event"] == "WORM_VIOLATION"
    assert "new raw file appeared" in v["reason"]
    assert v["data"]["before"] is None


def test_multiple_violations_all_reported(fake_project):
    before = snapshot_manifest(fake_project)
    # Modify one, remove one, add one
    (fake_project / "data" / "today.json").write_text("{}", encoding="utf-8")
    (fake_project / "data" / "snapshots" / "rollup_2026-05.json").unlink()
    (fake_project / "data" / "branches" / "1101.json").write_text("{}", encoding="utf-8")
    violations = verify_manifest(fake_project, before)
    kinds = sorted(v["reason"].split(":")[0] for v in violations)
    assert len(violations) == 3
    assert kinds == [
        "new raw file appeared during ingest",
        "raw file modified during ingest",
        "raw file removed during ingest",
    ]


def test_manifest_paths_are_relative_to_root(fake_project):
    m = snapshot_manifest(fake_project)
    for key in m.keys():
        # No absolute paths in the manifest
        assert not key.startswith("/"), f"manifest key {key!r} must be relative"
        assert key.startswith("data/"), f"manifest key {key!r} must start with 'data/'"


def test_empty_project_returns_empty_manifest(tmp_path):
    # No data/ dir at all
    assert snapshot_manifest(tmp_path) == {}
    assert verify_manifest(tmp_path, {}) == []
