"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.client import build_server_params, build_servers_config


def test_build_server_params_stdio_success():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = McpServerConfig(
        type="stdio",
        command="npx",
        args=["-y", "my-mcp-server"],
        env={"API_KEY": "secret"},
    )

    params = build_server_params("my-server", config)

    assert params == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "my-mcp-server"],
        "env": {"API_KEY": "secret"},
    }


def test_extensions_config_resolves_env_variables_inside_nested_collections(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MCP_TOKEN", "secret")
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    raw_config = {
        "args": ["--token", "$MCP_TOKEN", {"nested": ["$MCP_TOKEN", "$MISSING_TOKEN"]}],
        "tuple_args": ("$MCP_TOKEN", "$MISSING_TOKEN"),
        "env": {"API_KEY": "$MCP_TOKEN"},
        "enabled": True,
        "timeout": 30,
    }

    resolved = ExtensionsConfig.resolve_env_variables(raw_config)

    assert resolved["args"] == ["--token", "secret", {"nested": ["secret", ""]}]
    assert resolved["tuple_args"] == ("secret", "")
    assert resolved["env"] == {"API_KEY": "secret"}
    assert resolved["enabled"] is True
    assert resolved["timeout"] == 30


def test_build_server_params_stdio_requires_command():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = McpServerConfig(type="stdio", command=None)

    with pytest.raises(ValueError, match="requires 'command' field"):
        build_server_params("broken-stdio", config)


@pytest.mark.parametrize("transport", ["sse", "http"])
def test_build_server_params_http_like_success(transport: str):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = McpServerConfig(
        type=transport,
        url="https://example.com/mcp",
        headers={"Authorization": "Bearer token"},
    )

    params = build_server_params("remote-server", config)

    assert params == {
        "transport": transport,
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer token"},
    }


@pytest.mark.parametrize("transport", ["sse", "http"])
def test_build_server_params_http_like_requires_url(transport: str):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = McpServerConfig(type=transport, url=None)

    with pytest.raises(ValueError, match="requires 'url' field"):
        build_server_params("broken-remote", config)


def test_build_server_params_rejects_unsupported_transport():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = McpServerConfig(type="websocket")

    with pytest.raises(ValueError, match="unsupported transport type"):
        build_server_params("bad-transport", config)


@pytest.mark.parametrize("transport", ["sse", "http"])
def test_mcp_server_config_accepts_transport_alias(transport: str):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = McpServerConfig.model_validate(
        {
            "transport": transport,
            "url": "https://example.com/mcp",
        }
    )

    assert config.type == transport

    params = build_server_params("aliased-server", config)
    assert params["transport"] == transport
    assert params["url"] == "https://example.com/mcp"


def test_mcp_server_config_type_takes_precedence_over_transport():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = McpServerConfig.model_validate(
        {
            "type": "http",
            "transport": "sse",
            "url": "https://example.com/mcp",
        }
    )

    assert config.type == "http"


def test_build_servers_config_returns_empty_when_no_enabled_servers():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    extensions = ExtensionsConfig(
        mcp_servers={
            "disabled-a": McpServerConfig(enabled=False, type="stdio", command="echo"),
            "disabled-b": McpServerConfig(enabled=False, type="http", url="https://example.com"),
        },
        skills={},
    )

    assert build_servers_config(extensions) == {}


def test_build_servers_config_skips_invalid_server_and_keeps_valid_ones():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    extensions = ExtensionsConfig(
        mcp_servers={
            "valid-stdio": McpServerConfig(enabled=True, type="stdio", command="npx", args=["server"]),
            "invalid-stdio": McpServerConfig(enabled=True, type="stdio", command=None),
            "disabled-http": McpServerConfig(enabled=False, type="http", url="https://disabled.example.com"),
        },
        skills={},
    )

    result = build_servers_config(extensions)

    assert "valid-stdio" in result
    assert result["valid-stdio"]["transport"] == "stdio"
    assert "invalid-stdio" not in result
    assert "disabled-http" not in result


def test_build_server_params_excludes_tool_call_timeout():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = McpServerConfig(
        type="stdio",
        command="npx",
        args=["-y", "my-mcp-server"],
        tool_call_timeout=30.0,
    )

    params = build_server_params("my-server", config)

    assert "tool_call_timeout" not in params
    assert params == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "my-mcp-server"],
    }
