'定义 tools 模块提供的职责与可复用接口'
import json

from langchain.tools import tool
from tavily import TavilyClient

from deerflow.config import get_app_config


def _get_tavily_client() -> TavilyClient:
    '执行 _get_tavily_client 的明确职责，并返回与调用约定一致的结果'
    config = get_app_config().get_tool_config("web_search")
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return TavilyClient(api_key=api_key)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    '执行 web_search_tool 的明确职责，并返回与调用约定一致的结果。\n\nSearch the web.\n\n    Args:\n        query: The query to search for.\n    '
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
    '执行 web_fetch_tool 的明确职责，并返回与调用约定一致的结果。\n\nFetch the contents of a web page at a given URL.\n    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.\n    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.\n    Do NOT add www. to URLs that do NOT have them.\n    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.\n\n    Args:\n        url: The URL to fetch the contents of.\n    '
    client = _get_tavily_client()
    res = client.extract([url])
    if "failed_results" in res and len(res["failed_results"]) > 0:
        return f"Error: {res['failed_results'][0]['error']}"
    elif "results" in res and len(res["results"]) > 0:
        result = res["results"][0]
        return f"# {result['title']}\n\n{result['raw_content'][:4096]}"
    else:
        return "Error: No results found"
