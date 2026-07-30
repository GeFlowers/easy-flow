"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_gateway_app_imports_first_without_subagent_import_cycle() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    backend_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(backend_root)}
    result = subprocess.run(
        [sys.executable, "-c", "from app.gateway.app import app"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def test_subagent_package_public_executor_exports_are_lazy_importable() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    backend_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(backend_root)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from deerflow.subagents import SubagentExecutor, SubagentResult; print(SubagentExecutor.__name__, SubagentResult.__name__)",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "SubagentExecutor SubagentResult" in result.stdout
