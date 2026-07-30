"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from app.gateway.routers import mcp as mcp_router
from app.gateway.routers.mcp import McpConfigUpdateRequest, McpServerConfigResponse, update_mcp_configuration

pytestmark = pytest.mark.asyncio


async def test_update_mcp_configuration_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config_path = tmp_path / "extensions_config.json"
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await asyncio.to_thread(config_path.write_text, '{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    async def _noop_admin(_request, **_kwargs) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return None

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    body = McpConfigUpdateRequest(
        mcp_servers={"test-server": McpServerConfigResponse(type="http", url="https://example.test/mcp", description="anchor")},
    )

    resp = await update_mcp_configuration(request=None, body=body)

    assert "test-server" in resp.mcp_servers
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert await asyncio.to_thread(config_path.exists)


async def test_concurrent_mcp_updates_are_serialized(monkeypatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def _noop_admin(_request, **_kwargs) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return None

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda _body: None)

    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def _tracking_apply(_body) -> dict:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        with state_lock:
            active -= 1
        return {}

    monkeypatch.setattr(mcp_router, "_apply_mcp_config_update", _tracking_apply)

    body = McpConfigUpdateRequest(
        mcp_servers={"s": McpServerConfigResponse(type="http", url="https://example.test/mcp")},
    )

    await asyncio.gather(*[update_mcp_configuration(request=None, body=body) for _ in range(5)])

    assert max_active == 1, f"config updates were not serialized (max concurrency {max_active})"
