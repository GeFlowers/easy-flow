"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio

_MISSING = object()
_EXECUTOR_IMPORT_MOCKS = (
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.models",
)


def _seed_skill(skills_root: Path) -> None:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    skill = skills_root / "public" / "demo"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: regression-test skill\n---\n# demo\n",
        encoding="utf-8",
    )


@contextmanager
def _real_subagent_executor() -> Iterator[type]:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    original_modules = {name: sys.modules.get(name, _MISSING) for name in _EXECUTOR_IMPORT_MOCKS}
    original_executor = sys.modules.get("deerflow.subagents.executor", _MISSING)
    parent_module = sys.modules.get("deerflow.subagents")
    original_parent_executor = getattr(parent_module, "executor", _MISSING) if parent_module is not None else _MISSING

    sys.modules.pop("deerflow.subagents.executor", None)
    for name in _EXECUTOR_IMPORT_MOCKS:
        sys.modules[name] = MagicMock()

    try:
        executor_module = importlib.import_module("deerflow.subagents.executor")
        yield executor_module.SubagentExecutor
    finally:
        if original_executor is _MISSING:
            sys.modules.pop("deerflow.subagents.executor", None)
        else:
            sys.modules["deerflow.subagents.executor"] = original_executor

        if parent_module is not None:
            if original_parent_executor is _MISSING:
                try:
                    delattr(parent_module, "executor")
                except AttributeError:
                    pass
            else:
                parent_module.executor = original_parent_executor

        for name, module in original_modules.items():
            if module is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


async def test_load_skills_via_to_thread_does_not_block_event_loop(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.config.skills_config import SkillsConfig
    from deerflow.subagents.config import SubagentConfig

    _seed_skill(tmp_path)

    with _real_subagent_executor() as SubagentExecutor:
        executor = SubagentExecutor(
            config=SubagentConfig(
                name="demo",
                description="Loads skills through the production async path.",
            ),
            tools=[],
            app_config=SimpleNamespace(skills=SkillsConfig(path=str(tmp_path))),
            parent_model="test-model",
        )

        skills = await executor._load_skills()

    assert isinstance(skills, list)
    assert any(s.name == "demo" for s in skills)
