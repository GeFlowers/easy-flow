"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import UUID

import pytest
from fastapi import FastAPI, Request

from app.channels.runtime_config_store import ChannelRuntimeConfigStore
from app.gateway.routers.channel_connections import (
    ChannelRuntimeConfigRequest,
    configure_channel_provider_runtime,
    disconnect_channel_provider_runtime,
)
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.channel_connections_config import ChannelConnectionsConfig

# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
importlib.import_module("app.channels.service")

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _stub_app_config():
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def _make_request(tmp_path) -> Request:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    app = FastAPI()
    app.state.channel_connections_config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    app.state.channels_config = {}
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    app.state.channel_runtime_config_store = store
    user = SimpleNamespace(id=UUID("11111111-2222-3333-4444-555555555555"), system_role="admin")
    return Request({"type": "http", "app": app, "headers": [], "state": {"user": user}})


async def test_configure_runtime_channel_does_not_block_event_loop(tmp_path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    request = await asyncio.to_thread(_make_request, tmp_path)

    response = await configure_channel_provider_runtime(
        "slack",
        ChannelRuntimeConfigRequest(values={"bot_token": "xoxb-ui", "app_token": "xapp-ui"}),
        request,
    )

    assert response.provider == "slack"
    store = request.app.state.channel_runtime_config_store
    assert await asyncio.to_thread(store.get_provider_config, "slack") == {
        "enabled": True,
        "bot_token": "xoxb-ui",
        "app_token": "xapp-ui",
    }


async def test_disconnect_runtime_channel_does_not_block_event_loop(tmp_path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    request = await asyncio.to_thread(_make_request, tmp_path)
    store = request.app.state.channel_runtime_config_store
    await asyncio.to_thread(
        store.set_provider_config,
        "slack",
        {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"},
    )
    request.app.state.channels_config = {
        "slack": {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"},
    }

    response = await disconnect_channel_provider_runtime("slack", request)

    assert response.provider == "slack"
    assert await asyncio.to_thread(store.get_provider_config, "slack") == {
        "enabled": False,
        "_runtime_disabled": True,
    }


async def test_runtime_config_store_file_is_owner_only(tmp_path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    path = tmp_path / "channels" / "runtime-config.json"
    store = await asyncio.to_thread(ChannelRuntimeConfigStore, path)

    await asyncio.to_thread(
        store.set_provider_config,
        "slack",
        {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"},
    )

    mode = await asyncio.to_thread(lambda: path.stat().st_mode & 0o777)
    assert mode == 0o600


async def test_runtime_config_store_overwrites_loose_existing_file(tmp_path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    path = tmp_path / "channels" / "runtime-config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)

    store = await asyncio.to_thread(ChannelRuntimeConfigStore, path)
    await asyncio.to_thread(
        store.set_provider_config,
        "slack",
        {"enabled": True, "bot_token": "xoxb-ui"},
    )

    mode = await asyncio.to_thread(lambda: path.stat().st_mode & 0o777)
    assert mode == 0o600


async def test_runtime_config_store_chmod_failure_is_logged_not_fatal(tmp_path, caplog) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    path = tmp_path / "channels" / "runtime-config.json"
    store = await asyncio.to_thread(ChannelRuntimeConfigStore, path)

    real_chmod = Path.chmod

    def chmod_spy(self: Path, mode: int, *args, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        if self.suffix == ".tmp":
            raise OSError("chmod unsupported on this filesystem")
        return real_chmod(self, mode, *args, **kwargs)

    def _save_with_failing_temp_chmod() -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        with caplog.at_level(logging.DEBUG, logger="app.channels.runtime_config_store"), mock.patch.object(Path, "chmod", chmod_spy):
            store.set_provider_config("slack", {"enabled": True, "bot_token": "xoxb-ui"})

    await asyncio.to_thread(_save_with_failing_temp_chmod)

    assert any("Unable to chmod temporary channel runtime config store" in record.getMessage() for record in caplog.records)
    mode = await asyncio.to_thread(lambda: path.stat().st_mode & 0o777)
    assert mode == 0o600
    assert await asyncio.to_thread(store.get_provider_config, "slack") == {"enabled": True, "bot_token": "xoxb-ui"}
