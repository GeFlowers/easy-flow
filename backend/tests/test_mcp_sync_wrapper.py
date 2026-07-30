"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""
import asyncio
import contextvars
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deerflow.mcp.tools import get_mcp_tools
from deerflow.tools.sync import make_sync_tool_wrapper


class MockArgs(BaseModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    x: int = Field(..., description="test param")


def test_mcp_tool_sync_wrapper_generation():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def mock_coro(x: int):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return f"result: {x}"

    mock_tool = StructuredTool(
        name="test_tool",
        description="test description",
        args_schema=MockArgs,
        func=None,  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        coroutine=mock_coro,
    )

    mock_client_instance = MagicMock()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])

    with (
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file"),
        patch("deerflow.mcp.tools.build_servers_config", return_value={"test-server": {}}),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
    ):
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        tools = asyncio.run(get_mcp_tools())

        assert len(tools) == 1
        patched_tool = tools[0]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert patched_tool.func is not None

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = patched_tool.func(x=42)
        assert result == "result: 42"


def test_mcp_tool_loading_skips_failed_server():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def mock_coro(x: int):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return f"result: {x}"

    good_tool = StructuredTool(
        name="good-server_search",
        description="search from healthy server",
        args_schema=MockArgs,
        func=None,
        coroutine=mock_coro,
    )

    async def get_tools_for_server(*, server_name: str | None = None):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        if server_name == "good-server":
            return [good_tool]
        if server_name == "bad-server":
            raise RuntimeError("SSE endpoint returned text/html")
        raise AssertionError(f"unexpected server_name: {server_name}")

    mock_client_instance = MagicMock()
    mock_client_instance.get_tools = AsyncMock(side_effect=get_tools_for_server)

    with (
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", return_value=MagicMock(model_extra={})),
        patch("deerflow.mcp.tools.build_servers_config", return_value={"good-server": {}, "bad-server": {}}),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("deerflow.mcp.tools.logger.warning") as mock_warning,
    ):
        tools = asyncio.run(get_mcp_tools())

    assert [tool.name for tool in tools] == ["good-server_search"]
    assert tools[0].func is not None
    mock_warning.assert_called_once()
    assert "bad-server" in mock_warning.call_args[0][0]


def test_mcp_tool_sync_wrapper_in_running_loop():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def mock_coro(x: int):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        await asyncio.sleep(0.01)
        return f"async_result: {x}"

    sync_func = make_sync_tool_wrapper(mock_coro, "test_tool")

    async def run_in_loop():
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return sync_func(x=100)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    result = asyncio.run(run_in_loop())
    assert result == "async_result: 100"


def test_sync_wrapper_preserves_contextvars_in_running_loop():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    current_value: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_value", default=None)

    async def mock_coro() -> str | None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return current_value.get()

    sync_func = make_sync_tool_wrapper(mock_coro, "test_tool")

    async def run_in_loop() -> str | None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        token = current_value.set("from-parent-context")
        try:
            return sync_func()
        finally:
            current_value.reset(token)

    assert asyncio.run(run_in_loop()) == "from-parent-context"


def test_sync_wrapper_preserves_runnable_config_injection():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    captured: dict[str, object] = {}

    async def mock_coro(x: int, config: RunnableConfig = None):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        captured["thread_id"] = ((config or {}).get("configurable") or {}).get("thread_id")
        return f"result: {x}"

    mock_tool = StructuredTool(
        name="test_tool",
        description="test description",
        args_schema=MockArgs,
        func=make_sync_tool_wrapper(mock_coro, "test_tool"),
        coroutine=mock_coro,
    )

    result = mock_tool.invoke({"x": 42}, config={"configurable": {"thread_id": "thread-123"}})

    assert result == "result: 42"
    assert captured["thread_id"] == "thread-123"


def test_sync_wrapper_preserves_regular_config_argument():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def mock_coro(config: str):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return config

    sync_func = make_sync_tool_wrapper(mock_coro, "test_tool")

    assert sync_func(config="user-config") == "user-config"


def test_mcp_tool_sync_wrapper_exception_logging():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def error_coro():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise ValueError("Tool failure")

    sync_func = make_sync_tool_wrapper(error_coro, "error_tool")

    with patch("deerflow.tools.sync.logger.error") as mock_log_error:
        with pytest.raises(ValueError, match="Tool failure"):
            sync_func()
        mock_log_error.assert_called_once()
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert mock_log_error.call_args[0][1] == "error_tool"
