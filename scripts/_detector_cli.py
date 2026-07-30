"""本脚本负责命令行。安全边界：仅处理显式指定的输入与路径，不作为常驻生产服务入口。"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from pathlib import Path

TEST_SUPPORT_PATH = Path(__file__).resolve().parents[1] / "backend" / "tests"


def run_detector(module_name: str, argv: Sequence[str] | None = None) -> int:
    """执行运行对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    if not TEST_SUPPORT_PATH.is_dir():
        raise RuntimeError(f"detector support path not found: {TEST_SUPPORT_PATH}; the scripts/ directory has moved relative to backend/tests")
    if str(TEST_SUPPORT_PATH) not in sys.path:
        sys.path.insert(0, str(TEST_SUPPORT_PATH))
    module = importlib.import_module(module_name)
    return module.main(argv)
