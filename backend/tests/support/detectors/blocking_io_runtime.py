"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from blockbuster import BlockBuster, BlockBusterFunction, BlockingError

_SCANNED_MODULES: tuple[str, ...] = ("app", "deerflow")

# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
_PROJECT_BLOCKING_RULES: tuple[tuple[str, BlockBusterFunction], ...] = ()


def _install_project_rules(bb: BlockBuster) -> None:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    for name, rule in _PROJECT_BLOCKING_RULES:
        bb.functions[name] = rule


@contextmanager
def detect_blocking_io_strict() -> Iterator[BlockBuster]:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    bb = BlockBuster(scanned_modules=list(_SCANNED_MODULES))
    _install_project_rules(bb)
    try:
        bb.activate()
        yield bb
    finally:
        bb.deactivate()


__all__ = ["BlockingError", "detect_blocking_io_strict"]
