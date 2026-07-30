"""覆盖本文件测试的输入约束、模拟边界与回归保护，确保测试仅记录既有行为。"""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_boxlite_is_optional_harness_dependency() -> None:
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    pyproject_path = Path(__file__).resolve().parents[1] / "packages" / "harness" / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    core_dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert not any(dep.startswith("boxlite") for dep in core_dependencies)
    assert any(dep.startswith("boxlite>=0.9.7") for dep in optional_dependencies["boxlite"])
