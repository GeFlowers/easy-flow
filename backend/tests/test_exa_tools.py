"""验证 Exa 社区搜索与网页抓取工具的结果规范化和失败边界。"""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_app_config():
    """提供包含搜索数量、检索类型与 API 密钥的工具配置替身。"""
    with patch("deerflow.community.exa.tools.get_app_config") as mock_config:
        tool_config = MagicMock()
        tool_config.model_extra = {
            "max_results": 5,
            "search_type": "auto",
            "contents_max_characters": 1000,
            "api_key": "test-api-key",
        }
        mock_config.return_value.get_tool_config.return_value = tool_config
        yield mock_config


@pytest.fixture
def mock_exa_client():
    """替换 Exa SDK 客户端，使请求参数和响应均可精确断言。"""
    with patch("deerflow.community.exa.tools.Exa") as mock_exa_cls:
        mock_client = MagicMock()
        mock_exa_cls.return_value = mock_client
        yield mock_client


class TestWebSearchTool:
    """验证网页搜索对配置、结果和上游异常的映射规则。"""
    def test_basic_search(self, mock_app_config, mock_exa_client):
        """验证基础搜索将标题、链接和多个高亮片段规范化为 JSON 结果。"""
        mock_result_1 = MagicMock()
        mock_result_1.title = "Test Title 1"
        mock_result_1.url = "https://example.com/1"
        mock_result_1.highlights = ["This is a highlight about the topic."]

        mock_result_2 = MagicMock()
        mock_result_2.title = "Test Title 2"
        mock_result_2.url = "https://example.com/2"
        mock_result_2.highlights = ["First highlight.", "Second highlight."]

        mock_response = MagicMock()
        mock_response.results = [mock_result_1, mock_result_2]
        mock_exa_client.search.return_value = mock_response

        from deerflow.community.exa.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test query"})
        parsed = json.loads(result)

        assert len(parsed) == 2
        assert parsed[0]["title"] == "Test Title 1"
        assert parsed[0]["url"] == "https://example.com/1"
        assert parsed[0]["snippet"] == "This is a highlight about the topic."
        assert parsed[1]["snippet"] == "First highlight.\nSecond highlight."

        mock_exa_client.search.assert_called_once_with(
            "test query",
            type="auto",
            num_results=5,
            contents={"highlights": {"max_characters": 1000}},
        )

    def test_search_with_custom_config(self, mock_exa_client):
        """验证搜索请求准确传递自定义类型、数量和高亮长度限制。"""
        with patch("deerflow.community.exa.tools.get_app_config") as mock_config:
            tool_config = MagicMock()
            tool_config.model_extra = {
                "max_results": 10,
                "search_type": "neural",
                "contents_max_characters": 2000,
                "api_key": "test-key",
            }
            mock_config.return_value.get_tool_config.return_value = tool_config

            mock_response = MagicMock()
            mock_response.results = []
            mock_exa_client.search.return_value = mock_response

            from deerflow.community.exa.tools import web_search_tool

            web_search_tool.invoke({"query": "neural search"})

            mock_exa_client.search.assert_called_once_with(
                "neural search",
                type="neural",
                num_results=10,
                contents={"highlights": {"max_characters": 2000}},
            )

    def test_search_with_no_highlights(self, mock_app_config, mock_exa_client):
        """验证缺失高亮字段时仍返回空摘要而不抛出异常。"""
        mock_result = MagicMock()
        mock_result.title = "No Highlights"
        mock_result.url = "https://example.com/empty"
        mock_result.highlights = None

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_exa_client.search.return_value = mock_response

        from deerflow.community.exa.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test"})
        parsed = json.loads(result)

        assert parsed[0]["snippet"] == ""

    def test_search_empty_results(self, mock_app_config, mock_exa_client):
        """验证上游空结果会序列化为稳定的空 JSON 数组。"""
        mock_response = MagicMock()
        mock_response.results = []
        mock_exa_client.search.return_value = mock_response

        from deerflow.community.exa.tools import web_search_tool

        result = web_search_tool.invoke({"query": "nothing"})
        parsed = json.loads(result)

        assert parsed == []

    def test_search_error_handling(self, mock_app_config, mock_exa_client):
        """验证上游搜索异常会转换为可呈现的错误文本。"""
        mock_exa_client.search.side_effect = Exception("API rate limit exceeded")

        from deerflow.community.exa.tools import web_search_tool

        result = web_search_tool.invoke({"query": "error"})

        assert result == "Error: API rate limit exceeded"


class TestWebFetchTool:
    """验证网页抓取的内容格式化、配置隔离与错误回退。"""
    def test_basic_fetch(self, mock_app_config, mock_exa_client):
        """验证成功抓取以标题和正文的标记格式返回内容。"""
        mock_result = MagicMock()
        mock_result.title = "Fetched Page"
        mock_result.text = "This is the page content."

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_exa_client.get_contents.return_value = mock_response

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nThis is the page content."
        mock_exa_client.get_contents.assert_called_once_with(
            ["https://example.com"],
            text={"max_characters": 4096},
        )

    def test_fetch_no_title(self, mock_app_config, mock_exa_client):
        """验证页面标题缺失时使用固定兜底标题，保持输出可读。"""
        mock_result = MagicMock()
        mock_result.title = None
        mock_result.text = "Content without title."

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_exa_client.get_contents.return_value = mock_response

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result.startswith("# Untitled\n\n")

    def test_fetch_no_results(self, mock_app_config, mock_exa_client):
        """验证抓取结果为空时返回明确错误而非空正文。"""
        mock_response = MagicMock()
        mock_response.results = []
        mock_exa_client.get_contents.return_value = mock_response

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com/404"})

        assert result == "Error: No results found"

    def test_fetch_error_handling(self, mock_app_config, mock_exa_client):
        """验证抓取 SDK 抛错会转换为稳定的错误文本。"""
        mock_exa_client.get_contents.side_effect = Exception("Connection timeout")

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: Connection timeout"

    def test_fetch_reads_web_fetch_config(self, mock_exa_client):
        """验证抓取工具读取自身配置项，不会误用搜索工具配置。"""
        with patch("deerflow.community.exa.tools.get_app_config") as mock_config:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "exa-fetch-key"}
            mock_config.return_value.get_tool_config.return_value = tool_config

            mock_result = MagicMock()
            mock_result.title = "Page"
            mock_result.text = "Content."
            mock_response = MagicMock()
            mock_response.results = [mock_result]
            mock_exa_client.get_contents.return_value = mock_response

            from deerflow.community.exa.tools import web_fetch_tool

            web_fetch_tool.invoke({"url": "https://example.com"})

            mock_config.return_value.get_tool_config.assert_any_call("web_fetch")

    def test_fetch_uses_independent_api_key(self, mock_exa_client):
        """验证混合供应商配置下，抓取客户端只使用自己的 API 密钥。"""
        with patch("deerflow.community.exa.tools.get_app_config") as mock_config:
            with patch("deerflow.community.exa.tools.Exa") as mock_exa_cls:
                mock_exa_cls.return_value = mock_exa_client
                fetch_config = MagicMock()
                fetch_config.model_extra = {"api_key": "exa-fetch-key"}

                def get_tool_config(name):
                    """按工具名返回抓取配置，模拟同名配置隔离边界。"""
                    if name == "web_fetch":
                        return fetch_config
                    return None

                mock_config.return_value.get_tool_config.side_effect = get_tool_config

                mock_result = MagicMock()
                mock_result.title = "Page"
                mock_result.text = "Content."
                mock_response = MagicMock()
                mock_response.results = [mock_result]
                mock_exa_client.get_contents.return_value = mock_response

                from deerflow.community.exa.tools import web_fetch_tool

                web_fetch_tool.invoke({"url": "https://example.com"})

                mock_exa_cls.assert_called_once_with(api_key="exa-fetch-key")

    def test_fetch_truncates_long_content(self, mock_app_config, mock_exa_client):
        """验证超长网页正文被截断至 4096 字符，避免输出无限膨胀。"""
        mock_result = MagicMock()
        mock_result.title = "Long Page"
        mock_result.text = "x" * 5000

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_exa_client.get_contents.return_value = mock_response

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        # 标题前缀长度不计入被截断为 4096 字符的正文。
        content_after_header = result.split("\n\n", 1)[1]
        assert len(content_after_header) == 4096
