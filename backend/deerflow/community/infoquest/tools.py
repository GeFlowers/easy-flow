'''读取 InfoQuest 工具配置，并将搜索、抓取和图片搜索请求委托给客户端。'''

from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

from .infoquest_client import InfoQuestClient

readability_extractor = ReadabilityExtractor()


def _get_infoquest_client() -> InfoQuestClient:
    '''汇总搜索、抓取和图片搜索各自的选项，创建统一客户端实例。'''
    search_config = get_app_config().get_tool_config("web_search")
    search_time_range = -1
    if search_config is not None and "search_time_range" in search_config.model_extra:
        search_time_range = search_config.model_extra.get("search_time_range")

    fetch_config = get_app_config().get_tool_config("web_fetch")
    fetch_time = -1
    if fetch_config is not None and "fetch_time" in fetch_config.model_extra:
        fetch_time = fetch_config.model_extra.get("fetch_time")
    fetch_timeout = -1
    if fetch_config is not None and "timeout" in fetch_config.model_extra:
        fetch_timeout = fetch_config.model_extra.get("timeout")
    navigation_timeout = -1
    if fetch_config is not None and "navigation_timeout" in fetch_config.model_extra:
        navigation_timeout = fetch_config.model_extra.get("navigation_timeout")

    image_search_config = get_app_config().get_tool_config("image_search")
    image_search_time_range = -1
    if image_search_config is not None and "image_search_time_range" in image_search_config.model_extra:
        image_search_time_range = image_search_config.model_extra.get("image_search_time_range")
    image_size = "i"
    if image_search_config is not None and "image_size" in image_search_config.model_extra:
        image_size = image_search_config.model_extra.get("image_size")

    return InfoQuestClient(
        search_time_range=search_time_range,
        fetch_timeout=fetch_timeout,
        fetch_navigation_timeout=navigation_timeout,
        fetch_time=fetch_time,
        image_search_time_range=image_search_time_range,
        image_size=image_size,
    )


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    '''搜索网络并返回与查询相关的资料。

    Args:
        query: 要检索的查询内容。
    '''

    client = _get_infoquest_client()
    return client.web_search(query)


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    '''读取指定网页的正文内容并返回给 agent。
    仅抓取用户直接提供或 web_search、web_fetch 工具结果中返回的完整原始网址。
    此工具无法访问需要身份验证的内容，例如私有 Google Docs 文档或需要登录的网页。
    不要给原本不含 www. 的网址添加该前缀。
    网址必须包含协议头：https://example.com 有效，而 example.com 无效。

    Args:
        url: 要读取内容的网页地址。
    '''
    client = _get_infoquest_client()
    result = client.fetch(url)
    if result.startswith("Error: "):
        return result
    article = readability_extractor.extract_article(result)
    return article.to_markdown()[:4096]


@tool("image_search", parse_docstring=True)
def image_search_tool(query: str) -> str:
    '''在线查找图像参考，帮助后续创作保持人物、物品和场景的视觉一致性。

    **适用场景：**
    - 生成人物或肖像前：搜索相似的姿势、表情和风格。
    - 生成具体物品或产品前：搜索准确的视觉参考。
    - 生成场景或地点前：搜索建筑或环境参考。
    - 生成时尚或服装图片前：搜索款式和细节参考。

    返回的图片地址可作为图像生成的参考素材，以明显改善生成质量。

    Args:
        query: 用于搜索图片的查询内容。
    '''
    client = _get_infoquest_client()
    return client.image_search(query)
