'定义 tools 模块提供的职责与可复用接口。\n\n\nWeb Search Tool - Search the web using DuckDuckGo (no API key required).\n'

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
    '执行 _normalize_backend 的明确职责，并返回与调用约定一致的结果'
    if backend is None:
        return DEFAULT_BACKEND
    if isinstance(backend, (list, tuple)):
        return ",".join(str(part).strip() for part in backend if str(part).strip()) or DEFAULT_BACKEND
    return str(backend).strip() or DEFAULT_BACKEND


def _normalize_setting(value: str | None, default: str) -> str:
    '执行 _normalize_setting 的明确职责，并返回与调用约定一致的结果'
    return str(value).strip() if value else default


def _backend_includes_wikipedia(backend: str | list[str] | tuple[str, ...] | None) -> bool:
    '执行 _backend_includes_wikipedia 的明确职责，并返回与调用约定一致的结果'
    backend = _normalize_backend(backend)
    return any(part.strip().lower() in WIKIPEDIA_BACKENDS for part in backend.split(","))


def _contains_codepoint(query: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    '执行 _contains_codepoint 的明确职责，并返回与调用约定一致的结果'
    return any(start <= ord(char) <= end for char in query for start, end in ranges)


def _infer_wikipedia_region(query: str) -> str:
    "执行 _infer_wikipedia_region 的明确职责，并返回与调用约定一致的结果。\n\nPick a valid Wikipedia language region when DDGS' worldwide region is used."
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
    "执行 _resolve_ddgs_region 的明确职责，并返回与调用约定一致的结果。\n\n\n    DDGS' wikipedia engine treats the second part of region as a Wikipedia\n    subdomain. Its default worldwide region, wt-wt, becomes wt.wikipedia.org.\n    "
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
    '执行 _search_text 的明确职责，并返回与调用约定一致的结果。\n\n\n    Execute text search using DuckDuckGo.\n\n    Args:\n        query: Search keywords\n        max_results: Maximum number of results\n        region: Search region\n        safesearch: Safe search level\n        backend: DDGS backend(s), e.g. "auto", "duckduckgo", or "duckduckgo,brave"\n\n    Returns:\n        List of search results\n    '
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
    '执行 web_search_tool 的明确职责，并返回与调用约定一致的结果。\n\nSearch the web for information. Use this tool to find current information, news, articles, and facts from the internet.\n\n    Args:\n        query: Search keywords describing what you want to find. Be specific for better results.\n        max_results: Maximum number of results to return. Default is 5.\n    '
    config = get_app_config().get_tool_config("web_search")
    region = DEFAULT_REGION
    safesearch = DEFAULT_SAFESEARCH
    backend = DEFAULT_BACKEND

    if config is not None:
        # Override tool call defaults from config if set.
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
