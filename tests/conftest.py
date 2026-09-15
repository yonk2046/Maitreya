"""共用 pytest 設定:註冊自訂 marker。

不使用 pytest.ini / pyproject.toml 的 [tool.pytest.ini_options](會改變 rootdir
判定行為),改在這裡用 pytest_configure 掛 marker——影響範圍最小。
"""
from __future__ import annotations


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: 對完整真實語料跑回測的重型測試;CI fast path 排除",
    )
