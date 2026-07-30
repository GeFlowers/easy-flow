"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from support.detectors.blocking_io_runtime import detect_blocking_io_strict

_BLOCKING_IO_TEST_ROOT = Path(__file__).resolve().parent


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, None, None]:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    if not _is_blocking_io_item(item) or item.get_closest_marker("allow_blocking_io") is not None:
        yield
        return

    with detect_blocking_io_strict():
        yield


def _is_blocking_io_item(item: pytest.Item) -> bool:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return Path(item.path).resolve().is_relative_to(_BLOCKING_IO_TEST_ROOT)
