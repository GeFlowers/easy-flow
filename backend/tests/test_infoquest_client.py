"""验证资讯检索客户端及工具的既有行为。"""

import json
from unittest.mock import MagicMock, patch

from deerflow.community.infoquest import tools
from deerflow.community.infoquest.infoquest_client import InfoQuestClient


class TestInfoQuestClient:
    """覆盖资讯检索客户端及其工具的基础搜索、抓取与结果清洗场景。"""

    def test_infoquest_client_initialization(self):
        """验证客户端使用默认值与自定义值时正确保存各项配置。"""
        # 使用默认参数进行测试
        client = InfoQuestClient()
        assert client.fetch_time == -1
        assert client.fetch_timeout == -1
        assert client.fetch_navigation_timeout == -1
        assert client.search_time_range == -1

        # 使用自定义参数进行测试
        client = InfoQuestClient(fetch_time=10, fetch_timeout=30, fetch_navigation_timeout=60, search_time_range=24)
        assert client.fetch_time == 10
        assert client.fetch_timeout == 30
        assert client.fetch_navigation_timeout == 60
        assert client.search_time_range == 24

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_fetch_success(self, mock_post):
        """验证抓取接口成功响应时返回读取到的网页内容。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({"reader_result": "<html><body>Test content</body></html>"})
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.fetch("https://example.com")

        assert result == "<html><body>Test content</body></html>"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://reader.infoquest.bytepluses.com"
        assert kwargs["json"]["url"] == "https://example.com"
        assert kwargs["json"]["format"] == "HTML"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_fetch_non_200_status(self, mock_post):
        """验证抓取接口返回非 200 状态码时生成包含状态与内容的错误信息。"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.fetch("https://example.com")

        assert result == "Error: fetch API returned status 404: Not Found"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_fetch_empty_response(self, mock_post):
        """验证抓取接口返回空响应时给出未找到结果的错误信息。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.fetch("https://example.com")

        assert result == "Error: no result found"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_web_search_raw_results_success(self, mock_post):
        """验证原始网页搜索接口成功时返回包含搜索结果的数据。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"organic": [{"title": "Test Result", "desc": "Test description", "url": "https://example.com"}]}}}], "images_results": []}}
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.web_search_raw_results("test query", "")

        assert "search_result" in result
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://search.infoquest.bytepluses.com"
        assert kwargs["json"]["query"] == "test query"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_web_search_success(self, mock_post):
        """验证网页搜索成功时将原始结果整理为预期结构化字符串。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"organic": [{"title": "Test Result", "desc": "Test description", "url": "https://example.com"}]}}}], "images_results": []}}
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.web_search("test query")

        # 检查结果是否为包含预期内容的有效结构化数据字符串。
        result_data = json.loads(result)
        assert len(result_data) == 1
        assert result_data[0]["title"] == "Test Result"
        assert result_data[0]["url"] == "https://example.com"

    def test_clean_results(self):
        """验证结果清洗方法可整理示例原始搜索结果。"""
        raw_results = [
            {
                "content": {
                    "results": {
                        "organic": [{"title": "Test Page", "desc": "Page description", "url": "https://example.com/page1"}],
                        "top_stories": {"items": [{"title": "Test News", "source": "Test Source", "time_frame": "2 hours ago", "url": "https://example.com/news1"}]},
                    }
                }
            }
        ]

        cleaned = InfoQuestClient.clean_results(raw_results)

        assert len(cleaned) == 2
        assert cleaned[0]["type"] == "page"
        assert cleaned[0]["title"] == "Test Page"
        assert cleaned[1]["type"] == "news"
        assert cleaned[1]["title"] == "Test News"

    @patch("deerflow.community.infoquest.tools._get_infoquest_client")
    def test_web_search_tool(self, mock_get_client):
        """验证网页搜索工具将查询交给客户端并原样返回结果。"""
        mock_client = MagicMock()
        mock_client.web_search.return_value = json.dumps([])
        mock_get_client.return_value = mock_client

        result = tools.web_search_tool.run("test query")

        assert result == json.dumps([])
        mock_get_client.assert_called_once()
        mock_client.web_search.assert_called_once_with("test query")

    @patch("deerflow.community.infoquest.tools._get_infoquest_client")
    def test_web_fetch_tool(self, mock_get_client):
        """验证网页抓取工具将客户端网页结果转换为预期文本。"""
        mock_client = MagicMock()
        mock_client.fetch.return_value = "<html><body>Test content</body></html>"
        mock_get_client.return_value = mock_client

        result = tools.web_fetch_tool.run("https://example.com")

        assert result == "# Untitled\n\nTest content"
        mock_get_client.assert_called_once()
        mock_client.fetch.assert_called_once_with("https://example.com")

    @patch("deerflow.community.infoquest.tools.get_app_config")
    def test_get_infoquest_client(self, mock_get_app_config):
        """验证客户端工厂从工具配置读取搜索、抓取和图片搜索参数。"""
        mock_config = MagicMock()
        # 将图片搜索配置加入模拟调用序列。
        mock_config.get_tool_config.side_effect = [
            MagicMock(model_extra={"search_time_range": 24}),  # 网页搜索配置
            MagicMock(model_extra={"fetch_time": 10, "timeout": 30, "navigation_timeout": 60}),  # 网页抓取配置
            MagicMock(model_extra={"image_search_time_range": 7, "image_size": "l"}),  # 图片搜索配置
        ]
        mock_get_app_config.return_value = mock_config

        client = tools._get_infoquest_client()

        assert client.search_time_range == 24
        assert client.fetch_time == 10
        assert client.fetch_timeout == 30
        assert client.fetch_navigation_timeout == 60
        assert client.image_search_time_range == 7
        assert client.image_size == "l"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_web_search_api_error(self, mock_post):
        """验证网页搜索接口抛出异常时返回错误信息。"""
        mock_post.side_effect = Exception("Connection error")

        client = InfoQuestClient()
        result = client.web_search("test query")

        assert "Error" in result

    def test_clean_results_with_image_search(self):
        """验证图片搜索结果清洗方法可提取图片地址与标题。"""
        raw_results = [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg", "title": "Test Image 1", "url": "https://example.com/page1"}]}}}]
        cleaned = InfoQuestClient.clean_results_with_image_search(raw_results)

        assert len(cleaned) == 1
        assert cleaned[0]["image_url"] == "https://example.com/image1.jpg"
        assert cleaned[0]["title"] == "Test Image 1"

    def test_clean_results_with_image_search_empty(self):
        """验证图片搜索结果为空时清洗方法返回空列表。"""
        raw_results = [{"content": {"results": {"images_results": []}}}]
        cleaned = InfoQuestClient.clean_results_with_image_search(raw_results)

        assert len(cleaned) == 0

    def test_clean_results_with_image_search_no_images(self):
        """验证缺少图片结果字段时清洗方法返回空列表。"""
        raw_results = [{"content": {"results": {"organic": [{"title": "Test Page"}]}}}]
        cleaned = InfoQuestClient.clean_results_with_image_search(raw_results)

        assert len(cleaned) == 0


class TestImageSearch:
    """覆盖资讯检索图片搜索接口、参数处理、错误处理及工具调用场景。"""

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_image_search_raw_results_success(self, mock_post):
        """验证原始图片搜索接口成功时返回包含搜索结果的数据。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg", "title": "Test Image", "url": "https://example.com/page1"}]}}}]}}
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.image_search_raw_results("test query")

        assert "search_result" in result
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://search.infoquest.bytepluses.com"
        assert kwargs["json"]["query"] == "test query"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_image_search_raw_results_with_parameters(self, mock_post):
        """验证原始图片搜索接口会提交全部有效参数。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg"}]}}}]}}
        mock_post.return_value = mock_response

        client = InfoQuestClient(image_search_time_range=30, image_size="l")
        client.image_search_raw_results(query="cat", site="unsplash.com", output_format="JSON")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["query"] == "cat"
        assert kwargs["json"]["time_range"] == 30
        assert kwargs["json"]["site"] == "unsplash.com"
        assert kwargs["json"]["image_size"] == "l"
        assert kwargs["json"]["format"] == "JSON"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_image_search_raw_results_invalid_time_range(self, mock_post):
        """验证非法时间范围与图片尺寸不会写入原始图片搜索请求。"""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"images_results": []}}}]}}
        mock_post.return_value = mock_response

        # 创建时间范围无效的客户端（应被忽略）
        client = InfoQuestClient(image_search_time_range=400, image_size="x")
        client.image_search_raw_results(
            query="test",
            site="",
        )

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["query"] == "test"
        assert "time_range" not in kwargs["json"]
        assert "image_size" not in kwargs["json"]

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_image_search_success(self, mock_post):
        """验证图片搜索成功时将原始结果整理为预期结构化字符串。"""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg", "title": "Test Image", "url": "https://example.com/page1"}]}}}]}}
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.image_search("cat")

        # 检查结果是否为包含预期内容的有效结构化数据字符串。
        result_data = json.loads(result)

        assert len(result_data) == 1

        assert result_data[0]["image_url"] == "https://example.com/image1.jpg"

        assert result_data[0]["title"] == "Test Image"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_image_search_with_all_parameters(self, mock_post):
        """验证图片搜索会提交全部可选参数。"""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg"}]}}}]}}
        mock_post.return_value = mock_response

        # 创建带有图片搜索参数的客户端
        client = InfoQuestClient(image_search_time_range=7, image_size="m")
        client.image_search(query="dog", site="flickr.com", output_format="JSON")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["query"] == "dog"
        assert kwargs["json"]["time_range"] == 7
        assert kwargs["json"]["site"] == "flickr.com"
        assert kwargs["json"]["image_size"] == "m"

    @patch("deerflow.community.infoquest.infoquest_client.requests.post")
    def test_image_search_api_error(self, mock_post):
        """验证图片搜索接口抛出异常时返回错误信息。"""
        mock_post.side_effect = Exception("Connection error")

        client = InfoQuestClient()
        result = client.image_search("test query")

        assert "Error" in result

    @patch("deerflow.community.infoquest.tools._get_infoquest_client")
    def test_image_search_tool(self, mock_get_client):
        """验证图片搜索工具将查询交给客户端并返回有效结构化结果。"""
        mock_client = MagicMock()
        mock_client.image_search.return_value = json.dumps([{"image_url": "https://example.com/image1.jpg"}])
        mock_get_client.return_value = mock_client

        result = tools.image_search_tool.run({"query": "test query"})

        # 检查结果是否为有效结构化数据字符串。
        result_data = json.loads(result)
        assert len(result_data) == 1
        assert result_data[0]["image_url"] == "https://example.com/image1.jpg"
        mock_get_client.assert_called_once()
        mock_client.image_search.assert_called_once_with("test query")

    # 此用例验证工具函数向客户端传递的查询参数边界。

    @patch("deerflow.community.infoquest.tools._get_infoquest_client")
    def test_image_search_tool_with_parameters(self, mock_get_client):
        """验证图片搜索工具忽略额外参数，仅向客户端传递查询内容。"""
        mock_client = MagicMock()
        mock_client.image_search.return_value = json.dumps([{"image_url": "https://example.com/image1.jpg"}])
        mock_get_client.return_value = mock_client

        # 将全部参数作为字典传入（额外参数将被忽略）
        tools.image_search_tool.run({"query": "sunset", "time_range": 30, "site": "unsplash.com", "image_size": "l"})

        mock_get_client.assert_called_once()
        # 图片搜索工具只会把查询文本传给客户端的图片搜索方法。
        # 站点参数默认使用空字符串。
        mock_client.image_search.assert_called_once_with("sunset")
