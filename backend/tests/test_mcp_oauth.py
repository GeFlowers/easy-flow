"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.oauth import OAuthTokenManager, build_oauth_tool_interceptor, get_initial_oauth_headers


class _MockResponse:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def __init__(self, payload: dict[str, Any]):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self._payload = payload

    def raise_for_status(self) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return None

    def json(self) -> dict[str, Any]:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return self._payload


class _MockAsyncClient:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def __init__(self, payload: dict[str, Any], post_calls: list[dict[str, Any]], **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self._payload = payload
        self._post_calls = post_calls

    async def __aenter__(self):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return False

    async def post(self, url: str, data: dict[str, Any]):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self._post_calls.append({"url": url, "data": data})
        return _MockResponse(self._payload)


def test_oauth_token_manager_fetches_and_caches_token(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return _MockAsyncClient(
            payload={
                "access_token": "token-123",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                }
            }
        }
    )

    manager = OAuthTokenManager.from_extensions_config(config)

    first = asyncio.run(manager.get_authorization_header("secure-http"))
    second = asyncio.run(manager.get_authorization_header("secure-http"))

    assert first == "Bearer token-123"
    assert second == "Bearer token-123"
    assert len(post_calls) == 1
    assert post_calls[0]["url"] == "https://auth.example.com/oauth/token"
    assert post_calls[0]["data"]["grant_type"] == "client_credentials"


def test_build_oauth_interceptor_injects_authorization_header(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return _MockAsyncClient(
            payload={
                "access_token": "token-abc",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-sse": {
                    "enabled": True,
                    "type": "sse",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                }
            }
        }
    )

    interceptor = build_oauth_tool_interceptor(config)
    assert interceptor is not None

    class _Request:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.server_name = "secure-sse"
            self.headers = {"X-Test": "1"}

        def override(self, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            updated = _Request()
            updated.server_name = self.server_name
            updated.headers = kwargs.get("headers")
            return updated

    captured: dict[str, Any] = {}

    async def _handler(request):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        captured["headers"] = request.headers
        return "ok"

    result = asyncio.run(interceptor(_Request(), _handler))

    assert result == "ok"
    assert captured["headers"]["Authorization"] == "Bearer token-abc"
    assert captured["headers"]["X-Test"] == "1"


def test_get_initial_oauth_headers(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return _MockAsyncClient(
            payload={
                "access_token": "token-initial",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                },
                "no-oauth": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://example.com/mcp",
                },
            }
        }
    )

    headers = asyncio.run(get_initial_oauth_headers(config))

    assert headers == {"secure-http": "Bearer token-initial"}
    assert len(post_calls) == 1


def test_get_initial_oauth_headers_one_failing_server_does_not_drop_others(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    class _FailingClient:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        async def __aenter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return self

        async def __aexit__(self, exc_type, exc, tb):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return False

        async def post(self, url: str, data: dict[str, Any]):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            raise RuntimeError("token endpoint unreachable")

    class _OkClient:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        def __init__(self, post_calls: list[dict[str, Any]], **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self._post_calls = post_calls

        async def __aenter__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return self

        async def __aexit__(self, exc_type, exc, tb):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return False

        async def post(self, url: str, data: dict[str, Any]):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self._post_calls.append({"url": url, "data": data})
            return _MockResponse(
                payload={
                    "access_token": "token-ok",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            )

    ok_post_calls: list[dict[str, Any]] = []

    def _client_factory(**kwargs):
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        if not hasattr(_client_factory, "_count"):
            _client_factory._count = 0  # type: ignore[attr-defined]
        _client_factory._count += 1  # type: ignore[attr-defined]
        if _client_factory._count == 1:  # type: ignore[attr-defined]
            return _FailingClient()
        return _OkClient(post_calls=ok_post_calls)

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "broken-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://broken.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.broken.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                },
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id-2",
                        "client_secret": "client-secret-2",
                    },
                },
            }
        }
    )

    headers = asyncio.run(get_initial_oauth_headers(config))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert headers == {"secure-http": "Bearer token-ok"}
    assert len(ok_post_calls) == 1


def test_oauth_refresh_token_rotation_persists_rotated_value(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return _MockAsyncClient(
            payload={
                "access_token": "at-1",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rt-rotated-1",
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "rotating-srv": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "refresh_token",
                        "refresh_token": "rt-original-seed",
                    },
                }
            }
        }
    )

    manager = OAuthTokenManager.from_extensions_config(config)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    monkeypatch.setattr(OAuthTokenManager, "_is_expiring", lambda self, token, oauth: True)

    first = asyncio.run(manager.get_authorization_header("rotating-srv"))
    assert first == "Bearer at-1"
    assert len(post_calls) == 1
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert post_calls[0]["data"]["refresh_token"] == "rt-original-seed"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    second = asyncio.run(manager.get_authorization_header("rotating-srv"))
    assert second == "Bearer at-1"
    assert len(post_calls) == 2
    assert post_calls[1]["data"]["refresh_token"] == "rt-rotated-1"
