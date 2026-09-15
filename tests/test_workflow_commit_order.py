"""守門員:daily.yml 的測試步驟必須排在資料 commit 之後。

2026-09-15 事故(docs/FAILURE-MODE-INDEX.md F-8):測試原本排在 commit 之前,
用 `continue-on-error: true` 保證「不擋資料」。但 continue-on-error 只處理
**步驟失敗**,處理不了 **job 層 timeout-minutes**:測試跑超過 30 分鐘時整個 job
被取消,後面的 commit 直接 skipped。9/2、9/7–9/11、9/14 共 7 個交易日的快照
都已建好、verify 也通過,全部卡在測試步驟被砍,隨 runner 銷毀。

這顆測試讓「把測試移回 commit 前面」這個看似無害的整理動作直接變紅。
"""
from __future__ import annotations

import pathlib

import yaml

_WORKFLOW = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows" / "daily.yml"


def _steps():
    wf = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return wf["jobs"]["daily"]["steps"]


def _index(steps, predicate, what):
    hits = [i for i, s in enumerate(steps) if predicate(s)]
    assert hits, f"daily.yml 找不到 {what} 步驟"
    return hits[0]


def test_tests_run_after_data_commit():
    steps = _steps()
    commit_i = _index(steps, lambda s: "git push" in str(s.get("run", "")), "資料 commit/push")
    for i, s in enumerate(steps):
        if "pytest" in str(s.get("run", "")) or "make test" in str(s.get("run", "")):
            assert i > commit_i, (
                f"測試步驟「{s.get('name')}」排在資料 commit 之前(第 {i} 步 < 第 {commit_i} 步)。"
                "job 層逾時會連帶 skip 掉 commit,已建好的快照會被丟棄 —— 見本檔 docstring。")


def test_test_step_has_its_own_timeout():
    """步驟層逾時要比 job 層短,失敗才會標在測試步驟上,而不是整個 job 顯示 cancelled
    (cancelled 看起來像資料遺失,會讓人誤判或麻痺)。"""
    wf = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    job_timeout = wf["jobs"]["daily"].get("timeout-minutes")
    for s in _steps():
        if "make test" in str(s.get("run", "")):
            t = s.get("timeout-minutes")
            assert t is not None, f"「{s.get('name')}」沒有步驟層 timeout-minutes"
            assert job_timeout is None or t < job_timeout, f"步驟逾時 {t} 應小於 job 逾時 {job_timeout}"
