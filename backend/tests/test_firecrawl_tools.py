"""验证当前测试文件覆盖的预期行为与边界条件。"""

import json
from unittest.mock import MagicMock, patch


class TestWebSearchTool:
    """归纳当前测试场景的预期行为。"""
    @patch("deerflow.community.firecrawl.tools.FirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_search_uses_web_search_config(self, mock_get_app_config, mock_firecrawl_cls):
        """验证当前测试场景的预期行为。"""
        search_config = MagicMock()
        search_config.model_extra = {"api_key": "firecrawl-search-key", "max_results": 7}
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = [
            MagicMock(title="Result", url="https://example.com", description="Snippet"),
        ]
        mock_firecrawl_cls.return_value.search.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test query"})

        assert json.loads(result) == [
            {
                "title": "Result",
                "url": "https://example.com",
                "snippet": "Snippet",
            }
        ]
        mock_get_app_config.return_value.get_tool_config.assert_called_with("web_search")
        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-search-key")
        mock_firecrawl_cls.return_value.search.assert_called_once_with("test query", limit=7)


class TestWebFetchTool:
    """归纳当前测试场景的预期行为。"""
    @patch("deerflow.community.firecrawl.tools.FirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_fetch_uses_web_fetch_config(self, mock_get_app_config, mock_firecrawl_cls):
        """验证当前测试场景的预期行为。"""
        fetch_config = MagicMock()
        fetch_config.model_extra = {"api_key": "firecrawl-fetch-key"}

        def get_tool_config(name):
            """验证当前测试场景的预期行为。"""
            if name == "web_fetch":
                return fetch_config
            return None

        mock_get_app_config.return_value.get_tool_config.side_effect = get_tool_config

        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = "Fetched markdown"
        mock_scrape_result.metadata = MagicMock(title="Fetched Page")
        mock_firecrawl_cls.return_value.scrape.return_value = mock_scrape_result

        from deerflow.community.firecrawl.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nFetched markdown"
        mock_get_app_config.return_value.get_tool_config.assert_any_call("web_fetch")
        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-fetch-key")
        mock_firecrawl_cls.return_value.scrape.assert_called_once_with(
            "https://example.com",
            formats=["markdown"],
        )
