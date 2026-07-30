"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import httpx
import pytest

import app.channels.github as github_channel_module
from app.channels.github import GitHubChannel
from app.channels.manager import CHANNEL_CAPABILITIES
from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.service import _CHANNEL_REGISTRY


def test_github_channel_registered() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert _CHANNEL_REGISTRY["github"] == "app.channels.github:GitHubChannel"


def test_github_channel_capabilities_non_streaming() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert CHANNEL_CAPABILITIES["github"]["supports_streaming"] is False


def test_github_channel_does_not_import_writeback() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    # 说明当前测试分支所验证的真实行为与边界。
    assert "app.gateway.github.writeback" not in dir(github_channel_module)


@pytest.mark.asyncio
async def test_start_subscribes_outbound_and_stop_unsubscribes() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={"enabled": True})

    assert channel.is_running is False
    assert bus._outbound_listeners == []

    await channel.start()
    assert channel.is_running is True
    assert bus._outbound_listeners == [channel._on_outbound]

    await channel.stop()
    assert channel.is_running is False
    assert bus._outbound_listeners == []


@pytest.mark.asyncio
async def test_send_never_posts_to_github(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={})

    tripwire = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "request", tripwire)

    out = OutboundMessage(
        channel_name="github",
        chat_id="zhfeng/llm-gateway",
        thread_id="t-1",
        text="Hello from the agent.",
        metadata={
            "github": {
                "repo": "zhfeng/llm-gateway",
                "number": 7,
                "installation_id": 1234,
            }
        },
    )
    with caplog.at_level(logging.INFO, logger="app.channels.github"):
        await channel.send(out)

    tripwire.assert_not_awaited()
    assert any("final message from agent for zhfeng/llm-gateway#7" in rec.message and "not posted" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_send_logs_empty_body_at_info(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={})

    tripwire = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "request", tripwire)

    out = OutboundMessage(
        channel_name="github",
        chat_id="a/b",
        thread_id="t",
        text="",
        metadata={"github": {"repo": "a/b", "number": 1, "installation_id": 1}},
    )
    with caplog.at_level(logging.DEBUG, logger="app.channels.github"):
        await channel.send(out)

    tripwire.assert_not_awaited()
    assert any("text_len=0" in rec.message for rec in caplog.records)
    assert not any("final body" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_send_tolerates_missing_metadata(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={})

    tripwire = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "request", tripwire)

    out = OutboundMessage(
        channel_name="github",
        chat_id="a/b",
        thread_id="t",
        text="hi",
        metadata={},  # 说明当前测试分支所验证的真实行为与边界。
    )
    with caplog.at_level(logging.INFO, logger="app.channels.github"):
        await channel.send(out)

    tripwire.assert_not_awaited()
    # 说明当前测试分支所验证的真实行为与边界。
    assert any("a/b" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_send_handles_non_dict_github_metadata(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={})

    tripwire = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "request", tripwire)

    out = OutboundMessage(
        channel_name="github",
        chat_id="a/b",
        thread_id="t",
        text="hi",
        metadata={"github": "not-a-dict"},
    )
    with caplog.at_level(logging.INFO, logger="app.channels.github"):
        await channel.send(out)

    tripwire.assert_not_awaited()
    assert any("a/b" in rec.message for rec in caplog.records)
