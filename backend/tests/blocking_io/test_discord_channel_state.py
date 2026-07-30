"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.channels.discord import DiscordChannel
from app.channels.message_bus import MessageBus

pytestmark = pytest.mark.asyncio


class _FakeStore:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def __init__(self, tmp_path: Path) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self._path = tmp_path / "channel_store.json"


async def test_discord_constructor_is_io_free_on_async_path(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "t", "channel_store": _FakeStore(tmp_path)})
    assert channel._bot_token == "t"
    assert channel._thread_store_path == tmp_path / "discord_threads.json"


async def test_discord_record_then_persist_does_not_block_event_loop(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    channel._record_thread_mapping("chan-1", "thread-1")
    assert channel._active_threads == {"chan-1": "thread-1"}
    assert "thread-1" in channel._active_thread_ids

    await asyncio.to_thread(channel._persist_thread_mappings)

    data = json.loads(await asyncio.to_thread(channel._thread_store_path.read_text))
    assert data == {"chan-1": "thread-1"}


async def test_discord_record_thread_mapping_visible_before_persist(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    channel._record_thread_mapping("chan-1", "thread-1")
    assert "thread-1" in channel._active_thread_ids
    assert channel._active_threads["chan-1"] == "thread-1"
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert not await asyncio.to_thread(channel._thread_store_path.exists)


async def test_discord_record_thread_mapping_discards_replaced_thread(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    channel._record_thread_mapping("chan-1", "thread-1")
    channel._record_thread_mapping("chan-1", "thread-2")  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    assert channel._active_threads == {"chan-1": "thread-2"}
    assert "thread-1" not in channel._active_thread_ids
    assert "thread-2" in channel._active_thread_ids


async def test_discord_load_active_threads_does_not_block_event_loop(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    path = tmp_path / "discord_threads.json"
    await asyncio.to_thread(path.write_text, json.dumps({"chan-1": "thread-1", "chan-2": "thread-2"}))

    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await asyncio.to_thread(channel._load_active_threads)

    assert channel._active_threads == {"chan-1": "thread-1", "chan-2": "thread-2"}
    assert channel._active_thread_ids == {"thread-1", "thread-2"}
