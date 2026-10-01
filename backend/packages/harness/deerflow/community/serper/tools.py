'''使用 Serper 搜索网页和图片，规范供应商响应并过滤不安全的图片地址。'''

import json
import logging
import os
from ipaddress import IPv4Address, ip_address
from urllib.parse import urlparse

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_SERPER_SEARCH_ENDPOINT = "https://google.serper.dev/search"
_SERPER_IMAGES_ENDPOINT = "https://google.serper.dev/images"
_SERPER_MAX_RESULTS = 10
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str) -> str | None:
    '''优先从工具配置读取密钥，再回退到 SERPER_API_KEY 环境变量。'''
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = config.model_extra.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("SERPER_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _coerce_max_results(value: object, default: int = 5, max_allowed: int = _SERPER_MAX_RESULTS) -> int:
    '''把结果数量转换为正整数并限制在服务端允许范围内，错误输入采用默认值。'''
    try:
        count = int(value)
    except (TypeError, ValueError):
        return default
    if count <= 0:
        return default
    return min(count, max_allowed)


def _missing_key_error(query: str, tool_name: str) -> str:
    '''首次发现指定工具缺少密钥时记录提示，并返回结构化配置错误。'''
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning("Serper API key is not set for '%s'. Set SERPER_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://serper.dev", tool_name)
    return json.dumps(
        {"error": "SERPER_API_KEY is not configured", "query": query},
        ensure_ascii=False,
    )


def _unexpected_format_error(query: str) -> str:
    '''构造统一的供应商响应格式错误，保留原始查询供调用方诊断。'''
    return json.dumps(
        {"error": "Serper returned an unexpected response format", "query": query},
        ensure_ascii=False,
    )


def _response_items(data: dict, field: str, query: str) -> tuple[list[dict] | None, str | None]:
    '''提取供应商响应中的结果数组；缺失字段视为空结果，其他类型视为格式错误。'''
    items = data.get(field)
    if items is None:
        return [], None
    if not isinstance(items, list):
        logger.error("Serper returned unexpected '%s' payload type: %s", field, type(items).__name__)
        return None, _unexpected_format_error(query)
    return [item for item in items if isinstance(item, dict)], None


def _clean_query(query: str) -> str:
    '''去除查询首尾空白，并截断超过服务端长度限制的内容。'''
    query = query.strip()
    if len(query) > 500:
        query = query[:500]
    return query


def _decode_ipv4(host: str) -> IPv4Address | None:
    '''识别十进制、十六进制或八进制形式的非标准 IPv4 字面量，防止其绕过地址过滤。'''
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None

    values: list[int] = []
    for part in parts:
        if not part:
            return None
        try:
            if part.startswith(("0x", "0X")):
                values.append(int(part, 16))
            elif part.startswith("0") and len(part) > 1:
                values.append(int(part, 8))
            else:
                values.append(int(part, 10))
        except ValueError:
            return None

    *leading, last = values
    for value in leading:
        if not 0 <= value <= 0xFF:
            return None
    max_last = (1 << (8 * (4 - len(leading)))) - 1
    if not 0 <= last <= max_last:
        return None

    result = 0
    for value in leading:
        result = (result << 8) | value
    result = (result << (8 * (4 - len(leading)))) | last
    return ip_address(result)


def _is_url_present(value: object) -> bool:
    '''判断供应商字段是否提供了非空网址，以区分缺失字段和被安全过滤的字段。'''
    return isinstance(value, str) and bool(value.strip())


def _safe_public_url(value: object) -> str:
    '''仅保留公共 HTTP 或 HTTPS 地址，并拒绝本机、私有及混淆表示的非公网 IP 字面量。'''
    if not isinstance(value, str):
        return ""
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        return ""

    host = parsed.hostname.lower().rstrip(".")
    if not host:
        return ""
    if host == "localhost" or host.endswith(".localhost"):
        return ""

    try:
        ip = ip_address(host)
    except ValueError:
        ip = _decode_ipv4(host)
        if ip is None:
            return url
    return url if ip.is_global else ""


def _serper_post(endpoint: str, api_key: str, query: str, max_results: int) -> tuple[dict | None, str | None]:
    '''向指定搜索端点发送请求并解析对象响应；将网络、状态码及响应格式错误序列化返回。'''
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": max_results}

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error("Serper returned an unexpected payload type: %s", type(data).__name__)
            return None, _unexpected_format_error(query)
        return data, None
    except httpx.HTTPStatusError as e:
        resp_text = (e.response.text or "")[:500]
        logger.error("Serper API returned HTTP %s: %s", e.response.status_code, resp_text)
        return None, json.dumps(
            {"error": f"Serper API error: HTTP {e.response.status_code}", "query": query},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("Serper request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, json.dumps({"error": str(e)[:500], "query": query}, ensure_ascii=False)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    '''通过 Serper 调用 Google Search 查询网络信息。

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5, capped at 10.
    '''
    config = get_app_config().get_tool_config("web_search")
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", max_results)
    max_results = _coerce_max_results(max_results)
    query = _clean_query(query)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error(query, "web_search")

    data, error_json = _serper_post(_SERPER_SEARCH_ENDPOINT, api_key, query, max_results)
    if error_json is not None:
        return error_json

    organic, error_json = _response_items(data, "organic", query)
    if error_json is not None:
        return error_json
    if not organic:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "content": r.get("snippet", ""),
        }
        for r in organic[:max_results]
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


@tool("image_search", parse_docstring=True)
def image_search_tool(query: str, max_results: int = 5) -> str:
    '''通过 Serper 查询 Google 图片，为人物、物品或场景创作收集视觉参考。

    The returned image URLs can be used as reference images in image generation to significantly improve quality.

    Args:
        query: Search keywords describing the images you want to find. Be specific for better results (e.g., "Japanese woman street photography 1990s" instead of just "woman").
        max_results: Maximum number of images to return. Default is 5, capped at 10.
    '''
    config = get_app_config().get_tool_config("image_search")
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", max_results)
    max_results = _coerce_max_results(max_results)
    query = _clean_query(query)

    api_key = _get_api_key("image_search")
    if not api_key:
        return _missing_key_error(query, "image_search")

    data, error_json = _serper_post(_SERPER_IMAGES_ENDPOINT, api_key, query, max_results)
    if error_json is not None:
        return error_json

    images, error_json = _response_items(data, "images", query)
    if error_json is not None:
        return error_json
    if not images:
        return json.dumps({"error": "No images found", "query": query}, ensure_ascii=False)

    normalized_results = []
    for r in images:
        raw_image = r.get("imageUrl")
        raw_thumb = r.get("thumbnailUrl")
        safe_image = _safe_public_url(raw_image)
        safe_thumb = _safe_public_url(raw_thumb)
        image_url = safe_image or (safe_thumb if not _is_url_present(raw_image) else "")
        thumbnail_url = safe_thumb or (safe_image if not _is_url_present(raw_thumb) else "")
        if not image_url and not thumbnail_url:
            continue
        normalized_results.append(
            {
                "title": r.get("title", ""),
                "image_url": image_url,
                "thumbnail_url": thumbnail_url,
            }
        )
        if len(normalized_results) >= max_results:
            break

    if not normalized_results:
        return json.dumps({"error": "No safe image URLs found", "query": query}, ensure_ascii=False)

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
        "usage_hint": "Use the 'image_url' values as reference images in image generation. Download them first if needed.",
    }
    return json.dumps(output, indent=2, ensure_ascii=False)
