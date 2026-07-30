"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT_MARKER = ".git"


def resolve_repo_root(start: Path) -> Path:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    resolved = start.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / REPO_ROOT_MARKER).exists():
            return candidate
    raise RuntimeError(f"could not resolve the repository root: no '{REPO_ROOT_MARKER}' marker found above {resolved}; refusing to guess scan paths")
