"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

pytestmark = pytest.mark.asyncio

_SKILL_MD = """---
name: loop-skill
description: Anchor fixture skill for the blocking-IO gate.
---

# Loop Skill

Drives the full install pipeline under the Blockbuster gate.
"""

_SUPPORT_MD = "Reference notes scanned by the per-file security pass.\n"


def _build_archive(archive: Path) -> None:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("loop-skill/SKILL.md", _SKILL_MD)
        zf.writestr("loop-skill/references/usage.md", _SUPPORT_MD)


async def test_install_skill_archive_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    archive = tmp_path / "loop-skill.skill"
    await asyncio.to_thread(_build_archive, archive)

    async def _allow_scan(content: str, *, executable: bool = False, location: str = "SKILL.md", app_config=None, static_findings=None):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return SimpleNamespace(decision="allow", reason="anchor stub")

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _allow_scan)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    storage = await asyncio.to_thread(LocalSkillStorage, host_path=str(tmp_path / "skills"))

    result = await storage.ainstall_skill_from_archive(archive)

    assert result["success"] is True
    assert result["skill_name"] == "loop-skill"
    installed_md = tmp_path / "skills" / "custom" / "loop-skill" / "SKILL.md"
    assert await asyncio.to_thread(installed_md.exists)
    assert await asyncio.to_thread((tmp_path / "skills" / "custom" / "loop-skill" / "references" / "usage.md").exists)
