"""守門員(guard):tests/*.py 中任何 test_* 函式,若原始碼直接呼叫
_load_snapshots()(對完整真實語料跑回測),就必須帶 @pytest.mark.slow
(或所在模組有 pytestmark = pytest.mark.slow)。

沒有這個守門員,未來有人在測試裡新增一次 _load_snapshots() 呼叫、忘記標
slow,CI fast path(`make test-fast` / `pytest -m "not slow"`)會悄悄把它
納入——而 chip_anchored 策略對完整語料回測的成本隨快照數約立方成長
(2026-09-15 量測:81 份快照單次 ~90 秒;momentum 策略同樣資料只要 0.14
秒),幾顆這種測試就能把 fast path 拖到逾時,正是
tests/test_workflow_commit_order.py 所鎖定那次事故(daily.yml 測試步驟被迫
搬到 commit 之後)的根因之一。

本檔只用 ast 掃原始碼,不 import 任何專案模組、不讀語料——必須很快。

限制(刻意):只抓「test_* 函式自己的原始碼」裡直接出現的 `_load_snapshots(`
呼叫;不追蹤透過 helper/fixture 間接呼叫的情形(那需要完整呼叫圖分析,
超出這顆快速守門員的範圍)。間接呼叫的重型測試由人工標記 + code review
把關,已標的清單見 tests/test_backtest_b1_fixes.py、
tests/test_backtest_cost_model.py、tests/test_backtest_v3.py。
"""
from __future__ import annotations

import ast
import pathlib

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_TARGET_CALL = "_load_snapshots("
_SELF = pathlib.Path(__file__).name


def _is_slow_mark_expr(node: ast.AST) -> bool:
    """True if `node` is the expression `pytest.mark.slow` (bare, not called)."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "slow"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _decorator_is_slow(dec: ast.AST) -> bool:
    if _is_slow_mark_expr(dec):
        return True
    if isinstance(dec, ast.Call) and _is_slow_mark_expr(dec.func):
        return True
    return False


def _module_has_slow_pytestmark(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue
        value = node.value
        if _is_slow_mark_expr(value):
            return True
        if isinstance(value, (ast.List, ast.Tuple)) and any(
            _is_slow_mark_expr(elt) for elt in value.elts
        ):
            return True
    return False


def _find_violations(path: pathlib.Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    module_slow = _module_has_slow_pytestmark(tree)
    violations: list[str] = []

    def _walk(nodes):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                segment = ast.get_source_segment(source, node) or ""
                if _TARGET_CALL in segment:
                    has_slow = module_slow or any(_decorator_is_slow(d) for d in node.decorator_list)
                    if not has_slow:
                        violations.append(f"{path.name}::{node.name}")
            if isinstance(node, ast.ClassDef):
                _walk(node.body)

    _walk(tree.body)
    return violations


def test_all_real_corpus_backtests_are_marked_slow():
    violations: list[str] = []
    for path in sorted(_TESTS_DIR.glob("test_*.py")):
        if path.name == _SELF:
            continue
        violations.extend(_find_violations(path))

    assert not violations, (
        "以下測試函式的原始碼直接呼叫 _load_snapshots()(對完整真實語料跑回測),"
        "但沒有 @pytest.mark.slow(或模組層 pytestmark)標記:\n  "
        + "\n  ".join(violations)
        + "\n\n原因:完整語料回測(chip_anchored 策略)成本隨快照數約立方成長,"
        "沒標記會被 `pytest -m \"not slow\"` / `make test-fast` 誤收,"
        "把 CI fast path 拖到逾時(見 tests/test_workflow_commit_order.py 事故紀錄)。"
        "請幫這些函式補上 @pytest.mark.slow。"
    )
