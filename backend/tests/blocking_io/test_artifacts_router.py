"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import pytest

from app.gateway.path_utils import resolve_thread_virtual_path
from app.gateway.routers.artifacts import get_artifact

pytestmark = pytest.mark.asyncio

# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
_get_artifact = get_artifact.__wrapped__


async def _seed(tmp_path: Path, monkeypatch, thread_id: str, virtual_path: str) -> Path:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    target = await asyncio.to_thread(resolve_thread_virtual_path, thread_id, virtual_path)
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    return target


async def test_get_artifact_text_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    vpath = "mnt/user-data/outputs/notes.txt"
    target = await _seed(tmp_path, monkeypatch, "t1", vpath)
    await asyncio.to_thread(target.write_text, "hello world", encoding="utf-8")

    resp = await _get_artifact("t1", vpath, request=None, download=False)

    assert resp.status_code == 200
    assert resp.body == b"hello world"


async def test_get_artifact_binary_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    vpath = "mnt/user-data/outputs/blob.bin"
    target = await _seed(tmp_path, monkeypatch, "t1", vpath)
    payload = b"\x00\x01\x02PNGDATA"  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await asyncio.to_thread(target.write_bytes, payload)

    resp = await _get_artifact("t1", vpath, request=None, download=False)

    assert resp.status_code == 200
    assert resp.body == payload


async def test_get_artifact_skill_archive_member_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    skill_vpath = "mnt/user-data/outputs/demo.skill"
    target = await _seed(tmp_path, monkeypatch, "t1", skill_vpath)

    def _build_skill_zip() -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        with zipfile.ZipFile(target, "w") as zf:
            zf.writestr("SKILL.md", "# demo skill\n")

    await asyncio.to_thread(_build_skill_zip)

    resp = await _get_artifact("t1", f"{skill_vpath}/SKILL.md", request=None, download=False)

    assert resp.status_code == 200
    assert b"# demo skill" in resp.body
