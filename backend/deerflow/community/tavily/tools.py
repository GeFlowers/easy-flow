'''从应用配置读取密钥并创建 Tavily 搜索客户端。'''

import json

from langchain.tools import tool
from tavily import TavilyClient

from deerflow.config import get_app_config


def _get_tavily_client() -> TavilyClient:
    '''使用搜索工具配置中的密钥创建 Tavily 客户端。'''
    config = get_app_config().get_tool_config("web_search")
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return TavilyClient(api_key=api_key)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    '''搜索网络并返回与查询相关的资料。

    Args:
        query: 要检索的查询内容。
    '''
    config = get_app_config().get_tool_config("web_search")
    max_results = 5
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results")

    client = _get_tavily_client()
    res = client.search(query, max_results=max_results)
    normalized_results = [
        {
            "title": result["title"],
            "url": result["url"],
            "snippet": result["content"],
        }
        for result in res["results"]
    ]
    json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
    return json_results


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
    client = _get_tavily_client()
    res = client.extract([url])
    if "failed_results" in res and len(res["failed_results"]) > 0:
        return f"Error: {res['failed_results'][0]['error']}"
    elif "results" in res and len(res["results"]) > 0:
        result = res["results"][0]
        return f"# {result['title']}\n\n{result['raw_content'][:4096]}"
    else:
        return "Error: No results found"
