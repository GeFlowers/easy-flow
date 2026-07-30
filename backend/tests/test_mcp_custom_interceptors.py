"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from deerflow.mcp.tools import get_mcp_tools


def _make_patches(*, interceptor_paths=None):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=[])

    extra = {}
    if interceptor_paths is not None:
        extra["mcpInterceptors"] = interceptor_paths

    return {
        "client_cls": patch(
            "langchain_mcp_adapters.client.MultiServerMCPClient",
            return_value=mock_client,
        ),
        "from_file": patch(
            "deerflow.config.extensions_config.ExtensionsConfig.from_file",
            return_value=MagicMock(
                model_extra=extra,
                get_enabled_mcp_servers=MagicMock(return_value={}),
            ),
        ),
        "build_servers": patch(
            "deerflow.mcp.tools.build_servers_config",
            return_value={"test-server": {}},
        ),
        "oauth_headers": patch(
            "deerflow.mcp.tools.get_initial_oauth_headers",
            new_callable=AsyncMock,
            return_value={},
        ),
        "oauth_interceptor": patch(
            "deerflow.mcp.tools.build_oauth_tool_interceptor",
            return_value=None,
        ),
    }


def _get_interceptors(mock_cls):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    kw = mock_cls.call_args
    return kw.kwargs.get("tool_interceptors") or kw[1].get("tool_interceptors", [])


def test_custom_interceptor_loaded_and_appended():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def fake_interceptor(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request)

    def fake_builder():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return fake_interceptor

    p = _make_patches(interceptor_paths=["my_package.auth:build_interceptor"])

    with (
        p["client_cls"] as mock_cls,
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        patch("deerflow.mcp.tools.resolve_variable", return_value=fake_builder),
    ):
        asyncio.run(get_mcp_tools())

        interceptors = _get_interceptors(mock_cls)
        assert len(interceptors) == 1
        assert interceptors[0] is fake_interceptor


def test_multiple_custom_interceptors():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def interceptor_a(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request)

    async def interceptor_b(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request)

    builders = {
        "pkg.a:build_a": lambda: interceptor_a,
        "pkg.b:build_b": lambda: interceptor_b,
    }

    p = _make_patches(interceptor_paths=["pkg.a:build_a", "pkg.b:build_b"])

    with (
        p["client_cls"] as mock_cls,
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        patch("deerflow.mcp.tools.resolve_variable", side_effect=lambda path: builders[path]),
    ):
        asyncio.run(get_mcp_tools())

        interceptors = _get_interceptors(mock_cls)
        assert len(interceptors) == 2
        assert interceptors[0] is interceptor_a
        assert interceptors[1] is interceptor_b


def test_custom_interceptor_builder_returning_none_is_skipped():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    p = _make_patches(interceptor_paths=["pkg.noop:build_noop"])

    with (
        p["client_cls"] as mock_cls,
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        patch("deerflow.mcp.tools.resolve_variable", return_value=lambda: None),
    ):
        asyncio.run(get_mcp_tools())

        assert len(_get_interceptors(mock_cls)) == 0


def test_custom_interceptor_resolve_error_logs_warning_and_continues():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    p = _make_patches(interceptor_paths=["broken.path:does_not_exist"])

    with (
        p["client_cls"],
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        patch("deerflow.mcp.tools.resolve_variable", side_effect=ImportError("no such module")),
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        tools = asyncio.run(get_mcp_tools())

        assert tools == []
        mock_warn.assert_called_once()
        assert "broken.path:does_not_exist" in mock_warn.call_args[0][0]


def test_custom_interceptor_builder_exception_logs_warning_and_continues():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    def exploding_builder():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise RuntimeError("builder exploded")

    p = _make_patches(interceptor_paths=["pkg.bad:exploding_builder"])

    with (
        p["client_cls"],
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        patch("deerflow.mcp.tools.resolve_variable", return_value=exploding_builder),
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        tools = asyncio.run(get_mcp_tools())

        assert tools == []
        mock_warn.assert_called_once()
        assert "pkg.bad:exploding_builder" in mock_warn.call_args[0][0]


def test_no_mcp_interceptors_field_is_safe():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    p = _make_patches(interceptor_paths=None)

    with (
        p["client_cls"] as mock_cls,
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
    ):
        asyncio.run(get_mcp_tools())

        assert len(_get_interceptors(mock_cls)) == 0


def test_custom_interceptor_coexists_with_oauth_interceptor():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def oauth_fn(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request)

    async def custom_fn(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request)

    p = _make_patches(interceptor_paths=["pkg.custom:build_custom"])

    with (
        p["client_cls"] as mock_cls,
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=oauth_fn),
        patch("deerflow.mcp.tools.resolve_variable", return_value=lambda: custom_fn),
    ):
        asyncio.run(get_mcp_tools())

        interceptors = _get_interceptors(mock_cls)
        assert len(interceptors) == 2
        assert interceptors[0] is oauth_fn
        assert interceptors[1] is custom_fn


def test_mcp_interceptors_single_string_is_normalized():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    async def fake_interceptor(request, handler):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return await handler(request)

    p = _make_patches(interceptor_paths="pkg.single:build_it")

    with (
        p["client_cls"] as mock_cls,
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        patch("deerflow.mcp.tools.resolve_variable", return_value=lambda: fake_interceptor),
    ):
        asyncio.run(get_mcp_tools())

        assert len(_get_interceptors(mock_cls)) == 1


def test_mcp_interceptors_invalid_type_logs_warning():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    p = _make_patches(interceptor_paths=42)

    with (
        p["client_cls"] as mock_cls,
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        asyncio.run(get_mcp_tools())

        assert len(_get_interceptors(mock_cls)) == 0
        mock_warn.assert_called_once()
        assert "must be a list" in mock_warn.call_args[0][0]


def test_custom_interceptor_non_callable_return_logs_warning():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    p = _make_patches(interceptor_paths=["pkg.bad:returns_string"])

    with (
        p["client_cls"] as mock_cls,
        p["from_file"],
        p["build_servers"],
        p["oauth_headers"],
        p["oauth_interceptor"],
        patch("deerflow.mcp.tools.resolve_variable", return_value=lambda: "not_a_callable"),
        patch("deerflow.mcp.tools.logger.warning") as mock_warn,
    ):
        asyncio.run(get_mcp_tools())

        assert len(_get_interceptors(mock_cls)) == 0
        mock_warn.assert_called_once()
        assert "non-callable" in mock_warn.call_args[0][0]
