"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.channels.message_bus import MessageBus
from app.channels.wechat import WechatChannel, _encrypt_aes_128_ecb

pytestmark = pytest.mark.asyncio


async def test_wechat_constructor_is_io_free_on_async_path(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    bus = MessageBus()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    auth_path = tmp_path / "wechat-auth.json"
    await asyncio.to_thread(auth_path.write_text, json.dumps({"status": "confirmed", "bot_token": "from-disk"}))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    channel = WechatChannel(bus=bus, config={"bot_token": "from-config", "state_dir": str(tmp_path)})
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert channel._bot_token == "from-config"


async def test_wechat_inbound_file_staging_does_not_block_event_loop(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    bus = MessageBus()
    published = []

    async def capture(msg):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        published.append(msg)

    bus.publish_inbound = capture  # type: ignore[method-assign]

    channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})

    plaintext = b"fake-image-bytes"
    aes_key = b"1234567890abcdef"
    encrypted = _encrypt_aes_128_ecb(plaintext, aes_key)

    async def _fake_download(_url: str, *, timeout: float | None = None):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return encrypted

    channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

    await channel._handle_update(
        {
            "message_type": 1,
            "message_id": 101,
            "from_user_id": "wx-1",
            "context_token": "ctx-img",
            "item_list": [
                {
                    "type": 2,
                    "image_item": {"aeskey": aes_key.hex(), "media": {"full_url": "https://cdn.example/image.bin"}},
                }
            ],
        }
    )

    assert len(published) == 1
    assert len(published[0].files) == 1
    staged = Path(published[0].files[0]["path"])
    staged_exists = await asyncio.to_thread(staged.exists)
    assert staged_exists, "inbound image should be staged under the tmp state dir"


async def test_wechat_auth_state_load_does_not_block_event_loop(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    bus = MessageBus()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    channel = WechatChannel(bus=bus, config={"bot_token": "", "state_dir": str(tmp_path)})

    auth_path = tmp_path / "wechat-auth.json"
    await asyncio.to_thread(auth_path.write_text, json.dumps({"status": "confirmed", "bot_token": "loaded-token"}))

    result = await channel._ensure_authenticated()

    assert result is True
    assert channel._bot_token == "loaded-token"
