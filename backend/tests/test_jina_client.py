"""验证第三方客户端异步抓取及其网页抓取工具调用边界。

覆盖网络状态、空响应、网络异常、认证头、代理配置和事件循环卸载，防止
上游服务失败时把异常泄漏给调用方，或让工具配置在传递给网络客户端时丢失。
"""

import logging
from unittest.mock import MagicMock

import httpx
import pytest

import deerflow.community.jina_ai.jina_client as jina_client_module
from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.community.jina_ai.tools import (
    _coerce_bool,
    _coerce_proxy,
    _coerce_timeout,
    web_fetch_tool,
)


@pytest.fixture
def jina_client():
    """为每个测试提供新的吉纳客户端，避免接口密钥告警状态之外的实例状态互相污染。"""
    return JinaClient()


@pytest.mark.anyio
async def test_crawl_success(jina_client, monkeypatch):
    """确认 200 响应会原样返回正文，而不会被错误分支包装。"""

    async def mock_post(self, url, **kwargs):
        """模拟网络客户端成功返回含超文本正文的响应，隔离真实网络。"""
        return httpx.Response(200, text="<html><body>Hello</body></html>", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result == "<html><body>Hello</body></html>"


@pytest.mark.anyio
async def test_crawl_non_200_status(jina_client, monkeypatch):
    """确认限流等非 200 响应会变成可供工具层展示的错误文本。"""

    async def mock_post(self, url, **kwargs):
        """模拟带请求对象的 429 响应，以触发状态码错误处理路径。"""
        return httpx.Response(429, text="Rate limited", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "429" in result


@pytest.mark.anyio
async def test_crawl_empty_response(jina_client, monkeypatch):
    """确认成功状态但空正文不会被误认为可用抓取结果。"""

    async def mock_post(self, url, **kwargs):
        """模拟正文为空的成功响应，检验空内容回归边界。"""
        return httpx.Response(200, text="", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "empty" in result.lower()


@pytest.mark.anyio
async def test_crawl_whitespace_only_response(jina_client, monkeypatch):
    """确认仅含空白符的正文与空正文同样被拒绝。"""

    async def mock_post(self, url, **kwargs):
        """模拟只含空白符的 200 响应。"""
        return httpx.Response(200, text="   \n  ", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "empty" in result.lower()


@pytest.mark.anyio
async def test_crawl_network_error(jina_client, monkeypatch):
    """确认连接失败被转换为错误结果，调用方无需捕获网络库异常。"""

    async def mock_post(self, url, **kwargs):
        """模拟连接被拒绝，覆盖请求尚未获得响应的失败路径。"""
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "failed" in result.lower()


@pytest.mark.anyio
async def test_crawl_transient_failure_logs_without_traceback(jina_client, monkeypatch, caplog):
    """确认短暂网络失败仅记录一条含异常类型的警告日志，且不附加回溯。"""

    async def mock_post(self, url, **kwargs):
        """模拟连接超时，验证可恢复失败的日志契约。"""
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    with caplog.at_level(logging.DEBUG, logger="deerflow.community.jina_ai.jina_client"):
        result = await jina_client.crawl("https://example.com")

    jina_records = [r for r in caplog.records if r.name == "deerflow.community.jina_ai.jina_client"]
    assert len(jina_records) == 1, f"expected exactly one log record, got {len(jina_records)}"
    record = jina_records[0]
    assert record.levelno == logging.WARNING, f"expected WARNING, got {record.levelname}"
    assert record.exc_info is None, "transient failures must not attach a traceback"
    assert "ConnectTimeout" in record.getMessage()
    assert result.startswith("Error:")
    assert "ConnectTimeout" in result


@pytest.mark.anyio
async def test_crawl_passes_headers(jina_client, monkeypatch):
    """确认返回格式和超时参数被编码为第三方服务所需请求头。"""
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        """记录请求头并返回成功响应，避免真实客户端请求。"""
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    await jina_client.crawl("https://example.com", return_format="markdown", timeout=30)
    assert captured_headers["X-Return-Format"] == "markdown"
    assert captured_headers["X-Timeout"] == "30"


@pytest.mark.anyio
async def test_crawl_passes_proxy_to_httpx_client(jina_client, monkeypatch):
    """确认显式代理会传给异步客户端，且默认仍允许读取环境代理。"""
    captured_client_kwargs = {}

    class MockAsyncClient:
        """替代网络库异步客户端，记录构造参数和异步上下文生命周期。"""

        def __init__(self, **kwargs):
            """保存客户端初始化参数，供断言检查代理和环境配置开关。"""
            captured_client_kwargs.update(kwargs)

        async def __aenter__(self):
            """模拟进入异步客户端上下文并返回自身。"""
            return self

        async def __aexit__(self, exc_type, exc, tb):
            """模拟退出上下文，不吞掉测试中的异常。"""
            return None

        async def post(self, url, **kwargs):
            """返回成功响应，使测试只观察客户端构造配置。"""
            return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await jina_client.crawl("https://example.com", proxy="http://127.0.0.1:7890")

    assert result == "ok"
    assert captured_client_kwargs["proxy"] == "http://127.0.0.1:7890"
    assert captured_client_kwargs["trust_env"] is True


@pytest.mark.anyio
async def test_crawl_can_disable_trust_env(jina_client, monkeypatch):
    """确认调用方可禁用环境代理发现，保证网络路径可复现。"""
    captured_client_kwargs = {}

    class MockAsyncClient:
        """记录禁用环境配置读取时构造参数的最小异步客户端替身。"""

        def __init__(self, **kwargs):
            """捕获传给客户端构造器的参数。"""
            captured_client_kwargs.update(kwargs)

        async def __aenter__(self):
            """进入模拟客户端上下文。"""
            return self

        async def __aexit__(self, exc_type, exc, tb):
            """退出模拟客户端上下文并保留异常传播行为。"""
            return None

        async def post(self, url, **kwargs):
            """返回成功响应，避免触发外部网络。"""
            return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await jina_client.crawl("https://example.com", trust_env=False)

    assert result == "ok"
    assert captured_client_kwargs == {"trust_env": False}


@pytest.mark.anyio
async def test_crawl_includes_api_key_when_set(jina_client, monkeypatch):
    """确认存在接口密钥时请求携带承载式认证头。"""
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        """保存认证请求头并返回成功响应。"""
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setenv("JINA_API_KEY", "test-key-123")
    await jina_client.crawl("https://example.com")
    assert captured_headers["Authorization"] == "Bearer test-key-123"


@pytest.mark.anyio
async def test_crawl_warns_once_when_api_key_missing(jina_client, monkeypatch, caplog):
    """确认缺失接口密钥的告警在同一进程只发出一次，避免日志洪泛。"""
    jina_client_module._api_key_warned = False

    async def mock_post(self, url, **kwargs):
        """返回成功响应，使断言仅覆盖缺失密钥的告警生命周期。"""
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.delenv("JINA_API_KEY", raising=False)

    with caplog.at_level(logging.WARNING, logger="deerflow.community.jina_ai.jina_client"):
        await jina_client.crawl("https://example.com")
        await jina_client.crawl("https://example.com")

    warning_count = sum(1 for record in caplog.records if "Jina API key is not set" in record.message)
    assert warning_count == 1


@pytest.mark.anyio
async def test_crawl_no_auth_header_without_api_key(jina_client, monkeypatch):
    """确认未配置接口密钥时不会发送空的认证请求头。"""
    jina_client_module._api_key_warned = False
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        """记录发送的请求头以验证认证头确实缺席。"""
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    await jina_client.crawl("https://example.com")
    assert "Authorization" not in captured_headers


@pytest.mark.anyio
async def test_web_fetch_tool_returns_error_on_crawl_failure(monkeypatch):
    """确认抓取失败文本由网页抓取工具原样短路返回，不再尝试正文提取。"""

    async def mock_crawl(self, url, **kwargs):
        """模拟吉纳服务返回限流错误文本而非抛出异常。"""
        return "Error: Jina API returned status 429: Rate limited"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert result.startswith("Error:")
    assert "429" in result


@pytest.mark.anyio
async def test_web_fetch_tool_returns_markdown_on_success(monkeypatch):
    """确认成功超文本会经提取后产出正文，而非被误标为错误。"""

    async def mock_crawl(self, url, **kwargs):
        """提供最小超文本文档，作为正文提取输入。"""
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert "Hello world" in result
    assert not result.startswith("Error:")


@pytest.mark.anyio
async def test_web_fetch_tool_forwards_proxy_and_trust_env(monkeypatch):
    """确认工具扩展配置会归一化后完整传给抓取方法，防止代理设置丢失。"""
    captured_crawl_kwargs = {}

    async def mock_crawl(self, url, **kwargs):
        """记录抓取参数并返回可提取的超文本。"""
        captured_crawl_kwargs.update(kwargs)
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_tool_config = MagicMock()
    mock_tool_config.model_extra = {
        "timeout": "20",
        "proxy": "http://host.docker.internal:7890",
        "trust_env": "false",
    }
    mock_config.get_tool_config.return_value = mock_tool_config
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    result = await web_fetch_tool.ainvoke("https://example.com")

    assert "Hello world" in result
    assert captured_crawl_kwargs == {
        "return_format": "html",
        "timeout": 20,
        "proxy": "http://host.docker.internal:7890",
        "trust_env": False,
    }


@pytest.mark.anyio
async def test_web_fetch_tool_ignores_empty_proxy(monkeypatch):
    """确认未展开环境变量产生的空代理不会传入网络客户端。"""
    captured_crawl_kwargs = {}

    async def mock_crawl(self, url, **kwargs):
        """记录归一化后的抓取参数并返回成功超文本。"""
        captured_crawl_kwargs.update(kwargs)
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_tool_config = MagicMock()
    mock_tool_config.model_extra = {"proxy": "   ", "trust_env": True}
    mock_config.get_tool_config.return_value = mock_tool_config
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    result = await web_fetch_tool.ainvoke("https://example.com")

    assert "Hello world" in result
    assert captured_crawl_kwargs["proxy"] is None
    assert captured_crawl_kwargs["trust_env"] is True


@pytest.mark.anyio
async def test_web_fetch_tool_offloads_extraction_to_thread(monkeypatch):
    """确认可读性提取经线程卸载，防止阻塞事件循环。"""
    import asyncio

    async def mock_crawl(self, url, **kwargs):
        """返回待提取的超文本，避免网络请求干扰线程卸载断言。"""
        return "<html><body><p>threaded</p></body></html>"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    to_thread_called = False
    original_to_thread = asyncio.to_thread

    async def tracking_to_thread(func, *args, **kwargs):
        """标记线程卸载调用后委托原函数，保留真实线程执行语义。"""
        nonlocal to_thread_called
        to_thread_called = True
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr("deerflow.community.jina_ai.tools.asyncio.to_thread", tracking_to_thread)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert to_thread_called, "extract_article must be called via asyncio.to_thread to avoid blocking the event loop"
    assert "threaded" in result


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (True, False, True),
        (False, True, False),
        ("true", False, True),
        ("YES", False, True),
        (" on ", False, True),
        ("1", False, True),
        ("false", True, False),
        ("No", True, False),
        ("off", True, False),
        ("0", True, False),
        ("maybe", True, True),
        ("maybe", False, False),
        (None, True, True),
        (123, False, False),
    ],
)
def test_coerce_bool(value, default, expected):
    """验证布尔归一化接受既定字面量，并将未知值回退到默认值。"""
    assert _coerce_bool(value, default) is expected


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (30, 10, 30),
        ("45", 10, 45),
        ("not-a-number", 10, 10),
        (True, 10, 10),
        (False, 10, 10),
        (None, 10, 10),
        (1.5, 10, 10),
    ],
)
def test_coerce_timeout(value, default, expected):
    """验证超时归一化只接受整数或数字字符串，拒绝布尔值和无效输入。"""
    assert _coerce_timeout(value, default) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
        ("  http://proxy:8080  ", "http://proxy:8080"),
        ("", None),
        ("   ", None),
        (None, None),
        (123, None),
    ],
)
def test_coerce_proxy(value, expected):
    """验证代理归一化会去除字符串空白，并将空值或非字符串转为无值。"""
    assert _coerce_proxy(value) == expected
