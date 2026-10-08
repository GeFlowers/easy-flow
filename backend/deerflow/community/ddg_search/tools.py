'''通过 DuckDuckGo 搜索网页，并规范化搜索地域和维基百科语言区域。'''

import json
import logging

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "auto"
DEFAULT_REGION = "wt-wt"
DEFAULT_SAFESEARCH = "moderate"
DEFAULT_WIKIPEDIA_REGION = "us-en"

WIKIPEDIA_BACKENDS = {"auto", "all", "wikipedia"}
WIKIPEDIA_LANGUAGE_ALIASES = {
    "jp": "ja",
    "kr": "ko",
    "tzh": "zh",
    "wt": "en",
}


def _normalize_backend(backend: str | list[str] | tuple[str, ...] | None) -> str:
    '''把单个或多个搜索后端配置统一转换为逗号分隔字符串。'''
    if backend is None:
        return DEFAULT_BACKEND
    if isinstance(backend, (list, tuple)):
        return ",".join(str(part).strip() for part in backend if str(part).strip()) or DEFAULT_BACKEND
    return str(backend).strip() or DEFAULT_BACKEND


def _normalize_setting(value: str | None, default: str) -> str:
    '''清理字符串配置值；空值时使用指定默认值。'''
    return str(value).strip() if value else default


def _backend_includes_wikipedia(backend: str | list[str] | tuple[str, ...] | None) -> bool:
    '''判断后端配置中是否包含维基百科搜索引擎。'''
    backend = _normalize_backend(backend)
    return any(part.strip().lower() in WIKIPEDIA_BACKENDS for part in backend.split(","))


def _contains_codepoint(query: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    '''检查查询中的任一字符是否落入指定的 Unicode 码位范围。'''
    return any(start <= ord(char) <= end for char in query for start, end in ranges)


def _infer_wikipedia_region(query: str) -> str:
    '''根据查询字符推断 DDGS 维基百科引擎可识别的语言区域。'''
    if _contains_codepoint(query, ((0x3040, 0x30FF), (0x31F0, 0x31FF))):
        return "jp-ja"
    if _contains_codepoint(query, ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))):
        return "kr-ko"
    if _contains_codepoint(query, ((0x3400, 0x9FFF),)):
        return "cn-zh"
    if _contains_codepoint(query, ((0x0400, 0x04FF),)):
        return "ru-ru"
    if _contains_codepoint(query, ((0x0370, 0x03FF),)):
        return "gr-el"
    if _contains_codepoint(query, ((0x0590, 0x05FF),)):
        return "il-he"
    if _contains_codepoint(query, ((0x0600, 0x06FF),)):
        return "xa-ar"
    return DEFAULT_WIKIPEDIA_REGION


def _resolve_ddgs_region(query: str, region: str | None, backend: str | list[str] | tuple[str, ...] | None) -> str:
    '''结合搜索后端、显式地域和查询文字确定 DDGS 使用的地域代码。'''
    normalized_region = _normalize_setting(region, DEFAULT_REGION).lower()
    if not _backend_includes_wikipedia(backend):
        return normalized_region

    if normalized_region == DEFAULT_REGION:
        return _infer_wikipedia_region(query)

    if "-" not in normalized_region:
        return DEFAULT_WIKIPEDIA_REGION

    country, language = normalized_region.split("-", 1)
    return f"{country}-{WIKIPEDIA_LANGUAGE_ALIASES.get(language, language)}"


def _search_text(
    query: str,
    max_results: int = 5,
    region: str | None = DEFAULT_REGION,
    safesearch: str | None = DEFAULT_SAFESEARCH,
    backend: str | list[str] | tuple[str, ...] | None = DEFAULT_BACKEND,
) -> list[dict]:
    '''调用 DDGS 文本搜索接口；依赖缺失或请求失败时记录错误并返回空列表。'''
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("ddgs library not installed. Run: pip install ddgs")
        return []

    ddgs = DDGS(timeout=30)

    try:
        backend = _normalize_backend(backend)
        safesearch = _normalize_setting(safesearch, DEFAULT_SAFESEARCH)
        effective_region = _resolve_ddgs_region(query, region, backend)
        results = ddgs.text(
            query,
            region=effective_region,
            safesearch=safesearch,
            max_results=max_results,
            backend=backend,
        )
        return list(results) if results else []

    except Exception as e:
        logger.error(f"Failed to search web: {e}")
        return []


@tool("web_search", parse_docstring=True)
def web_search_tool(
    query: str,
    max_results: int = 5,
) -> str:
    '''通过 DuckDuckGo 查询网络上的最新信息、新闻、文章或事实。

    Args:
        query: 描述检索目标的关键词；尽量具体以提高结果相关性。
        max_results: 返回结果的最大数量，默认值为 5。
    '''
    config = get_app_config().get_tool_config("web_search")
    region = DEFAULT_REGION
    safesearch = DEFAULT_SAFESEARCH
    backend = DEFAULT_BACKEND

    if config is not None:
        # 已配置的搜索选项覆盖工具参数中的默认值。
        max_results = config.model_extra.get("max_results", max_results)
        region = config.model_extra.get("region", region)
        safesearch = config.model_extra.get("safesearch", safesearch)
        backend = config.model_extra.get("backend", backend)

    results = _search_text(
        query=query,
        max_results=max_results,
        region=region,
        safesearch=safesearch,
        backend=backend,
    )

    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("href", r.get("link", "")),
            "content": r.get("body", r.get("snippet", "")),
        }
        for r in results
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }

    return json.dumps(output, indent=2, ensure_ascii=False)
