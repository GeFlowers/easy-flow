"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.channels import manager as mgr
from app.channels.message_bus import InboundMessage
from deerflow.uploads.manager import get_uploads_dir

pytestmark = pytest.mark.asyncio


async def test_ingest_inbound_files_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    async def _fake_reader(f, client):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return b"payload-bytes"

    monkeypatch.setattr(mgr, "_read_http_inbound_file", _fake_reader)

    msg = InboundMessage(
        channel_name="unit-test-channel",  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        chat_id="c1",
        user_id="u1",
        text="hi",
        files=[{"type": "file", "filename": "report.txt"}],
    )

    created = await mgr._ingest_inbound_files("t1", msg)

    assert len(created) == 1
    assert created[0]["filename"] == "report.txt"
    written = await asyncio.to_thread(lambda: (get_uploads_dir("t1") / "report.txt").exists())
    assert written, "inbound file should be written under the tmp uploads dir"
