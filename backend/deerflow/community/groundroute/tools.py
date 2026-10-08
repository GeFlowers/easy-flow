'''将 GroundRoute 搜索服务包装为代理可调用的网页搜索与正文获取工具。

GroundRoute（https://groundroute.ai）是整合 Serper、Brave、Exa、Tavily、
Firecrawl 和 Perplexity 六种搜索引擎的元搜索服务。它将查询路由到满足质量要求
且费用最低的引擎，并缓存重复查询。单个引擎不可用时可故障切换；按节省费用
分成的计费方式让调用方保留约一半的缓存收益。

本模块仅依赖 httpx，不使用 GroundRoute 专用客户端。`/v1/search` 的请求和
响应映射与 GroundRoute 的工具服务器及已验证的 Langflow 组件一致：
  results[] = {url, title, snippet, content, source_engine, published_at}

`web_search` 返回标准化的结构化列表，字段为 {title, url, snippet, source_engine}。
`web_fetch` 通过 GroundRoute 的 mode=page 读取单个网址并返回提取出的正文。
'''

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_GROUNDROUTE_ENDPOINT = "https://api.groundroute.ai/v1/search"
_DEFAULT_MAX_RESULTS = 5
_MAX_RESULTS_CAP = 50
_TIMEOUT_S = 30.0
_FETCH_SNIPPET_LIMIT = 4096
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str) -> str | None:
    '''先从当前工具对应的配置段读取密钥，再回退到环境变量。

    搜索和抓取可以使用不同服务商，因此按工具名称读取各自的配置。
    '''
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    return os.getenv("GROUNDROUTE_API_KEY")


def _coerce_max_results(value: object, *, default: int = _DEFAULT_MAX_RESULTS) -> int:
    '''将结果数配置转为整数并限制在服务端支持的 1 到 50 范围内。'''
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid GroundRoute max_results=%r; using default %s", value, default)
        coerced = default
    return max(1, min(coerced, _MAX_RESULTS_CAP))


def _missing_key_error(tool_name: str, **context: str) -> str:
    '''首次遇到工具缺少密钥时记录警告，并生成携带调用上下文的错误结果。'''
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "GroundRoute API key is not set for '%s'. Set GROUNDROUTE_API_KEY in your environment or provide api_key in config.yaml. Get a free key at https://groundroute.ai/keys",
            tool_name,
        )
    return json.dumps({"error": "GROUNDROUTE_API_KEY is not configured", **context}, ensure_ascii=False)


def _post_search(api_key: str, body: dict) -> dict:
    '''向 GroundRoute 搜索接口发送授权请求，并解析其 JSON 响应。'''
    with httpx.Client(timeout=_TIMEOUT_S) as client:
        response = client.post(
            _GROUNDROUTE_ENDPOINT,
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    response.raise_for_status()
    return response.json()


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int | None = None) -> str:
    '''通过 GroundRoute 搜索网络信息并返回结果。

    GroundRoute 在六种搜索引擎之间路由查询，返回所选引擎的结果集，
    某个引擎不可用时自动切换。

    Args:
        query: 描述检索目标的关键词；尽量具体以提高结果相关性。
        max_results: 返回搜索结果的最大数量；省略时使用配置值，默认值为 5，并限制在 1 到 50 范围内。
    '''
    # 优先使用调用参数；只有调用方未指定时才读取配置中的结果数。
    if max_results is None:
        config = get_app_config().get_tool_config("web_search")
        if config is not None:
            max_results = (config.model_extra or {}).get("max_results")
    count = _DEFAULT_MAX_RESULTS if max_results is None else _coerce_max_results(max_results)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error("web_search", query=query)

    try:
        data = _post_search(api_key, {"query": query, "max_results": count})
    except httpx.HTTPStatusError as e:
        logger.error("GroundRoute API returned HTTP %s: %s", e.response.status_code, e.response.text)
        return json.dumps(
            {"error": f"GroundRoute API error: HTTP {e.response.status_code}", "query": query},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("GroundRoute search failed: %s: %s", type(e).__name__, e)
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    results = data.get("results") or []
    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
            "source_engine": r.get("source_engine", ""),
        }
        for r in results
    ]
    return json.dumps(normalized_results, indent=2, ensure_ascii=False)


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    '''通过 GroundRoute 获取指定网址的网页正文。
    仅抓取用户直接提供或 web_search、web_fetch 工具结果中返回的完整原始网址。
    此工具无法访问需要身份验证的内容，例如私有 Google Docs 文档或需要登录的网页。
    不要给原本不含 www. 的网址添加该前缀。
    网址必须包含协议头：https://example.com 有效，而 example.com 无效。

    Args:
        url: 要读取内容的网页地址。
    '''
    api_key = _get_api_key("web_fetch")
    if not api_key:
        return _missing_key_error("web_fetch", url=url)

    try:
        data = _post_search(api_key, {"query": url, "mode": "page", "max_results": 1})
    except httpx.HTTPStatusError as e:
        logger.error("GroundRoute fetch returned HTTP %s: %s", e.response.status_code, e.response.text)
        return f"Error: GroundRoute API error: HTTP {e.response.status_code}"
    except Exception as e:
        logger.error("GroundRoute fetch failed: %s: %s", type(e).__name__, e)
        return f"Error: {e}"

    results = data.get("results") or []
    if not results:
        return "Error: No results found"

    result = results[0]
    content = result.get("content") or result.get("snippet") or ""
    title = result.get("title", "")
    return f"# {title}\n\n{content[:_FETCH_SNIPPET_LIMIT]}"
