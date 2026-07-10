"""Canonical Field Registry CI 對拍（憲法 Phase 0）。

比對「最新真實快照的實際欄位集合」vs「schema/field_registry.yaml 的登記」：

  - 快照中存在但 registry 未登記         → FAIL（擋未登記欄位進快照）
  - registry 標 active 但快照缺           → FAIL
  - deprecated-pending：可在可不在（殭屍欄 replay 生命週期內續存，不強制）
  - planned：尚未落地，不要求出現在快照（若真的出現也不失敗）

對拍分兩層：頂層 snapshot_fields、per-stock record_fields。

Phase 0 = additive only：本測試只讀 registry + 最新 reports/YYYY-MM-DD.json，
不改 schema、不動引擎、不碰 replay strip 清單。
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "schema" / "field_registry.yaml"
REPORTS_DIR = REPO_ROOT / "reports"

_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


def _latest_snapshot_path() -> Path:
    """最新一份 reports/YYYY-MM-DD.json（排除 .intelligence.json / index.json / .sha256）。"""
    candidates = [
        p for p in REPORTS_DIR.glob("*.json") if _SNAPSHOT_RE.match(p.name)
    ]
    if not candidates:
        pytest.skip("no reports/YYYY-MM-DD.json snapshot to compare against")
    return sorted(candidates)[-1]


def _load_registry() -> dict:
    with open(REGISTRY_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _by_status(entries: list[dict]) -> tuple[set[str], set[str], set[str], set[str]]:
    """回傳 (all_names, active, deprecated_pending, planned)。"""
    all_names, active, deprecated, planned = set(), set(), set(), set()
    for e in entries:
        name = e["name"]
        all_names.add(name)
        status = e.get("status", "active")
        if status == "active":
            active.add(name)
        elif status == "deprecated-pending":
            deprecated.add(name)
        elif status == "planned":
            planned.add(name)
    return all_names, active, deprecated, planned


@pytest.fixture(scope="module")
def registry() -> dict:
    return _load_registry()


@pytest.fixture(scope="module")
def snapshot() -> dict:
    with open(_latest_snapshot_path(), encoding="utf-8") as fh:
        return json.load(fh)


def test_registry_loads_and_is_wellformed(registry):
    assert "snapshot_fields" in registry
    assert "record_fields" in registry
    assert "planned_fields" in registry
    seen: set[str] = set()
    for section in ("snapshot_fields", "record_fields", "planned_fields"):
        for e in registry[section]:
            for key in ("name", "semantic", "state", "grain", "replay", "owner", "status"):
                assert key in e, f"{section} entry missing '{key}': {e}"
            assert e["state"] in {"I", "O", "M"}, e
            assert e["grain"] in {"ticker", "date", "sector"}, e
            assert e["replay"] in {"MUST-I", "epoch-scoped-O", "excluded-M"}, e
            assert e["status"] in {"active", "deprecated-pending", "planned"}, e
            # 全 registry 內欄名唯一（跨區也不得重複登記）
            assert e["name"] not in seen, f"duplicate field name: {e['name']}"
            seen.add(e["name"])


def test_snapshot_toplevel_matches_registry(registry, snapshot):
    all_reg, active, _deprecated, _planned = _by_status(registry["snapshot_fields"])
    _, _, _, planned_top = _by_status(registry["planned_fields"])
    actual = set(snapshot.keys())

    # 未登記欄位擋下（planned 名若真出現也放行）
    unregistered = actual - all_reg - planned_top
    assert not unregistered, (
        f"頂層快照有欄位未登記於 registry.snapshot_fields: {sorted(unregistered)}"
    )
    # active 登記但快照缺
    missing_active = active - actual
    assert not missing_active, (
        f"registry 標 active 的頂層欄位在快照中缺席: {sorted(missing_active)}"
    )


def test_snapshot_record_fields_match_registry(registry, snapshot):
    all_reg, active, _deprecated, _planned = _by_status(registry["record_fields"])
    _, _, _, planned_rec = _by_status(registry["planned_fields"])

    stocks = snapshot.get("stocks", [])
    if not stocks:
        pytest.skip("snapshot has no stocks[] to compare")
    actual: set[str] = set()
    for rec in stocks:
        actual |= set(rec.keys())

    unregistered = actual - all_reg - planned_rec
    assert not unregistered, (
        f"per-stock record 有欄位未登記於 registry.record_fields: {sorted(unregistered)}"
    )
    # active 欄必須至少在一檔 record 出現
    missing_active = active - actual
    assert not missing_active, (
        f"registry 標 active 的 record 欄位在所有 stocks 中缺席: {sorted(missing_active)}"
    )


def test_planned_fields_not_yet_landed(registry, snapshot):
    """planned = 尚未落地。若已出現在快照，代表落地了但忘了改 status（提醒，非硬擋）。"""
    _, _, _, planned = _by_status(registry["planned_fields"])
    top = set(snapshot.keys())
    rec: set[str] = set()
    for r in snapshot.get("stocks", []):
        rec |= set(r.keys())
    landed = planned & (top | rec)
    assert not landed, (
        f"以下欄位標 planned 但已出現在快照，請更新 registry status→active: {sorted(landed)}"
    )
