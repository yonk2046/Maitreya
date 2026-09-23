"""守門員:T9(b) —— 卡在本機的每日資料 commit 自癒(FAILURE-MODE F-17)。

8/31 與 9/17 各發生一次:push 失敗後本機留下 `data: daily pipeline` commit,
之後每晚開頭的 rebase 都撞衝突,Mac 備援長期失效,只能人工清。
自癒的紅線 = 只丟「origin 已經有同一份快照」的重複產出,且丟之前一定留備份分支。
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_HEAL = _ROOT / "deploy" / "heal_stranded_commits.sh"


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def _commit(repo: pathlib.Path, path: str, body: str, subject: str) -> None:
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", subject)


@pytest.fixture()
def clone(tmp_path):
    """一個 clone,其 origin/main 上已有 9/22 的快照;回傳 (clone 路徑, origin 路徑)。"""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-qb", "main")
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _commit(origin, "README.md", "x", "init")
    _commit(origin, "reports/2026-09-22.json", '{"origin":1}', "data: daily pipeline 2026-09-22")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    return work


def _run(repo: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(_HEAL)], cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace")


def test_nothing_ahead_is_a_clean_no_op(clone):
    assert _run(clone).returncode == 0
    assert _git(clone, "rev-list", "--count", "origin/main..HEAD") == "0"


def test_duplicate_data_commit_is_backed_up_and_dropped(clone):
    """本機重做了一份 origin 已發布的快照 → 丟掉,但先備份。"""
    _commit(clone, "reports/2026-09-22.json", '{"local":1}', "data: daily pipeline 2026-09-22")
    stranded = _git(clone, "rev-parse", "HEAD")

    r = _run(clone)
    assert r.returncode == 0, r.stderr
    assert _git(clone, "rev-parse", "HEAD") == _git(clone, "rev-parse", "origin/main")
    backups = [b.strip("* ") for b in _git(clone, "branch", "--list", "backup/stranded-*").splitlines()]
    assert len(backups) == 1
    assert _git(clone, "rev-parse", backups[0]) == stranded      # 丟掉的東西找得回來


def test_refuses_when_the_snapshot_exists_only_locally(clone):
    """origin 沒有這份快照 → 本機是唯一一份,絕不能丟。"""
    _commit(clone, "reports/2026-09-23.json", '{"local":1}', "data: daily pipeline 2026-09-23")
    head = _git(clone, "rev-parse", "HEAD")
    assert _run(clone).returncode == 1
    assert _git(clone, "rev-parse", "HEAD") == head
    assert _git(clone, "branch", "--list", "backup/stranded-*") == ""


def test_refuses_when_a_code_commit_is_stranded(clone):
    """混到程式碼 commit → 不自動處理。"""
    _commit(clone, "reports/2026-09-22.json", '{"local":1}', "data: daily pipeline 2026-09-22")
    _commit(clone, "core/thing.py", "print(1)", "fix: 某個修正")
    head = _git(clone, "rev-parse", "HEAD")
    assert _run(clone).returncode == 1
    assert _git(clone, "rev-parse", "HEAD") == head
