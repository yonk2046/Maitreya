"""守門員:launchd 的 stdout/stderr 不得被 git 追蹤(docs/FAILURE-MODE-INDEX.md F-16)。

2026-09-15 查出:`reports/_daily_logs/launchd.{out,err}.log` 被追蹤且永遠 dirty。
`deploy/daily_and_push.sh` 的 `git rebase --autostash` 會把它們收起來再還原,等於換掉
磁碟上的檔案,launchd 卻仍寫著已被刪除的舊檔 —— rebase 之後印的所有東西都消失。
6/23–9/15 共 63 行 log,除了 starting/python 兩行之外一行都沒留下(包括失敗訊息),
Mac 備援因此三個月都是看不見的。另外腳本的 `git add data/ reports/` 會把它們掃進資料 commit。
修法:`3d67801` + `2e416a1`(git rm --cached + .gitignore)。
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_LOGS = ("reports/_daily_logs/launchd.out.log", "reports/_daily_logs/launchd.err.log")


def _git(*args):
    return subprocess.run(["git", "-C", str(_ROOT), *args], capture_output=True, text=True)


@pytest.fixture(scope="module", autouse=True)
def _need_git_repo():
    if shutil.which("git") is None or _git("rev-parse", "--git-dir").returncode != 0:
        pytest.skip("不在 git repo 中,無法檢查追蹤狀態")


@pytest.mark.parametrize("path", _LOGS)
def test_launchd_log_is_not_tracked(path):
    tracked = _git("ls-files", "--error-unmatch", path).returncode == 0
    assert not tracked, (
        f"{path} 被 git 追蹤。追蹤中的 dirty 檔會被 `git rebase --autostash` 換掉,"
        "launchd 之後的輸出全部遺失 —— 見本檔 docstring。請 `git rm --cached` 並保留 .gitignore 規則。")


@pytest.mark.parametrize("path", _LOGS)
def test_launchd_log_is_gitignored(path):
    ignored = _git("check-ignore", "-q", "--no-index", path).returncode == 0
    assert ignored, f"{path} 沒有被 .gitignore 忽略,`git add data/ reports/` 會把它重新加回追蹤。"
