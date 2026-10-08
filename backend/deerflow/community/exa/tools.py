'''封装 Exa 搜索与网页正文获取工具，并读取各工具独立配置。'''

import json

from exa_py import Exa
from langchain.tools import tool

from deerflow.config import get_app_config


def _get_exa_client(tool_name: str = "web_search") -> Exa:
    '''从指定工具配置读取密钥并创建 Exa 客户端。'''
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return Exa(api_key=api_key)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    '''搜索网络并返回与查询相关的资料。

    Args:
        query: 要检索的查询内容。
    '''
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = 5
        search_type = "auto"
        contents_max_characters = 1000
        if config is not None:
            max_results = config.model_extra.get("max_results", max_results)
            search_type = config.model_extra.get("search_type", search_type)
            contents_max_characters = config.model_extra.get("contents_max_characters", contents_max_characters)

        client = _get_exa_client()
        res = client.search(
            query,
            type=search_type,
            num_results=max_results,
            contents={"highlights": {"max_characters": contents_max_characters}},
        )

        normalized_results = [
            {
                "title": result.title or "",
                "url": result.url or "",
                "snippet": "\n".join(result.highlights) if result.highlights else "",
            }
            for result in res.results
        ]
        json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
        return json_results
    except Exception as e:
        return f"Error: {str(e)}"


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
    try:
        client = _get_exa_client("web_fetch")
        res = client.get_contents([url], text={"max_characters": 4096})

        if res.results:
            result = res.results[0]
            title = result.title or "Untitled"
            text = result.text or ""
            return f"# {title}\n\n{text[:4096]}"
        else:
            return "Error: No results found"
    except Exception as e:
        return f"Error: {str(e)}"
