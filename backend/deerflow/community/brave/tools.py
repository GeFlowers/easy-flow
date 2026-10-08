'''通过 Brave Search 官方 API 提供网页搜索和图片搜索工具。'''

import json
import logging
import os
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from urllib.parse import urlparse

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_BRAVE_WEB_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_IMAGES_ENDPOINT = "https://api.search.brave.com/res/v1/images/search"
_DEFAULT_MAX_RESULTS = 5
# 网页搜索接口单次最多返回 20 条。
_BRAVE_WEB_MAX_COUNT = 20
# 图片搜索接口允许比网页搜索更大的批次。
_BRAVE_IMAGE_MAX_COUNT = 200
# 用于识别 NAT64 地址中嵌入的 IPv4 部分。
_NAT64_PREFIX = ip_network("64:ff9b::/96")
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str = "web_search") -> str | None:
    '''优先从工具配置读取 API 密钥，再回退到 BRAVE_SEARCH_API_KEY 环境变量。'''
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _coerce_max_results(
    value: object,
    *,
    default: int = _DEFAULT_MAX_RESULTS,
    max_allowed: int = _BRAVE_WEB_MAX_COUNT,
) -> int:
    '''将结果数转换为整数并限制在 API 支持范围内；无效值使用默认值。'''
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid Brave Search max_results=%r; using default %s",
            value,
            default,
        )
        coerced = default

    return max(1, min(coerced, max_allowed))


def _clean_query(query: str, *, max_length: int = 400) -> str:
    '''去除查询首尾空白，并截断超长搜索词。'''
    query = query.strip()
    if len(query) > max_length:
        query = query[:max_length]
    return query


def _missing_key_error(query: str, tool_name: str) -> str:
    '''按工具首次记录缺少密钥的警告，并返回 JSON 格式错误信息。'''
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "Brave Search API key is not set for '%s'. Set BRAVE_SEARCH_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://brave.com/search/api/",
            tool_name,
        )
    return json.dumps(
        {"error": "BRAVE_SEARCH_API_KEY is not configured", "query": query},
        ensure_ascii=False,
    )


def _unexpected_format_error(query: str, *, service_name: str = "Brave Search") -> str:
    '''生成第三方搜索服务响应结构不符合预期时的 JSON 错误。'''
    return json.dumps(
        {"error": f"{service_name} returned an unexpected response format", "query": query},
        ensure_ascii=False,
    )


def _decode_ipv4(host: str) -> IPv4Address | None:
    '''解析标准库不接受的整数、十六进制和八进制 IPv4 写法。'''
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
    return IPv4Address(result)


def _is_url_present(value: object) -> bool:
    '''判断搜索结果字段是否包含非空 URL 字符串。'''
    return isinstance(value, str) and bool(value.strip())


def _embedded_ipv4(ip: IPv6Address) -> IPv4Address | None:
    '''提取 IPv4 映射、6to4、NAT64 或兼容格式 IPv6 地址中嵌入的 IPv4。'''
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip in _NAT64_PREFIX:
        return IPv4Address(int(ip) & 0xFFFFFFFF)
    # 兼容形式的 IPv4 嵌入 IPv6；排除未指定地址和回环地址。
    packed = int(ip)
    if packed >> 32 == 0 and packed > 1:
        return IPv4Address(packed & 0xFFFFFFFF)
    return None


def _safe_public_url(value: object) -> str:
    '''仅返回 HTTP(S) 公网地址；拒绝本机、私有 IP 及嵌入非公网 IPv4 的 IPv6。

    此检查仅解析 URL 字符串，无法判断公网域名最终解析到的地址；真正下载时
    仍须再次校验解析后的 IP，避免 DNS 解析造成的 SSRF。
    '''
    if not isinstance(value, str):
        return ""
    url = value.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
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
    if isinstance(ip, IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None and not embedded.is_global:
            return ""
    return url if ip.is_global else ""


def _brave_get(
    endpoint: str,
    api_key: str,
    query: str,
    params: dict[str, object],
    *,
    service_name: str,
) -> tuple[dict | None, str | None]:
    '''发送带密钥的 Brave API 请求，返回对象数据或已格式化的错误响应。'''
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(endpoint, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error("%s returned an unexpected payload type: %s", service_name, type(data).__name__)
            return None, _unexpected_format_error(query, service_name=service_name)
        return data, None
    except httpx.HTTPStatusError as e:
        logger.error("%s API returned HTTP %s: %s", service_name, e.response.status_code, e.response.text)
        return None, json.dumps(
            {"error": f"{service_name} API error: HTTP {e.response.status_code}", "query": query},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("%s request failed: %s: %s", service_name, type(e).__name__, e)
        return None, json.dumps({"error": str(e), "query": query}, ensure_ascii=False)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    '''通过 Brave Search 查询网络信息并返回相关结果。

    Args:
        query: 描述检索目标的关键词，尽量具体以提高结果相关性。
        max_results: 返回结果的最大数量，默认值为 5。
    '''
    config = get_app_config().get_tool_config("web_search")
    if config is not None and "max_results" in (config.model_extra or {}):
        max_results = config.model_extra["max_results"]

    count = _coerce_max_results(max_results, max_allowed=_BRAVE_WEB_MAX_COUNT)
    query = _clean_query(query)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error(query, "web_search")

    params = {"q": query, "count": count, "text_decorations": False}

    data, error_json = _brave_get(_BRAVE_WEB_ENDPOINT, api_key, query, params, service_name="Brave Search")
    if error_json is not None:
        return error_json

    web_results = (data.get("web") or {}).get("results", [])
    if not web_results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("description", ""),
        }
        for r in web_results
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


@tool("image_search", parse_docstring=True)
def image_search_tool(query: str, max_results: int = 5) -> str:
    '''通过 Brave 图片搜索收集人物、物品或场景的视觉参考，供图像创作使用。

    返回的图片网址可作为图像生成的参考素材。

    Args:
        query: 描述所需图片内容的关键词，尽量具体以提高结果相关性。
        max_results: 返回图片的最大数量，默认值为 5，最多为 200。
    '''
    config = get_app_config().get_tool_config("image_search")
    extra = (config.model_extra or {}) if config is not None else {}
    if "max_results" in extra:
        max_results = extra["max_results"]
    count = _coerce_max_results(max_results, max_allowed=_BRAVE_IMAGE_MAX_COUNT)
    query = _clean_query(query)

    api_key = _get_api_key("image_search")
    if not api_key:
        return _missing_key_error(query, "image_search")

    params: dict[str, object] = {"q": query, "count": count}
    for key in ("country", "search_lang", "safesearch", "spellcheck"):
        if key in extra:
            params[key] = extra[key]

    data, error_json = _brave_get(
        _BRAVE_IMAGES_ENDPOINT,
        api_key,
        query,
        params,
        service_name="Brave Image Search",
    )
    if error_json is not None:
        return error_json

    images = data.get("results")
    if images is None:
        images = []
    if not isinstance(images, list):
        logger.error("Brave Image Search returned unexpected 'results' payload type: %s", type(images).__name__)
        return _unexpected_format_error(query, service_name="Brave Image Search")
    if not images:
        return json.dumps({"error": "No images found", "query": query}, ensure_ascii=False)

    normalized_results = []
    for item in images:
        if not isinstance(item, dict):
            continue
        thumbnail = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else {}
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        raw_image = properties.get("url")
        raw_thumb = thumbnail.get("src")
        raw_source = item.get("url")

        safe_image = _safe_public_url(raw_image)
        safe_thumb = _safe_public_url(raw_thumb)
        safe_source = _safe_public_url(raw_source)

        # 只从最终保留的网址来源读取宽高，避免尺寸与返回图片地址不匹配。
        if safe_image:
            image_url, image_dims = safe_image, properties
        elif not _is_url_present(raw_image):
            image_url, image_dims = safe_thumb, thumbnail
        else:
            image_url, image_dims = "", {}

        if safe_thumb:
            thumbnail_url, thumb_dims = safe_thumb, thumbnail
        elif not _is_url_present(raw_thumb):
            thumbnail_url, thumb_dims = safe_image, properties
        else:
            thumbnail_url, thumb_dims = "", {}

        if not image_url and not thumbnail_url:
            continue

        dims = image_dims if image_url else thumb_dims

        normalized_results.append(
            {
                "title": item.get("title", ""),
                "image_url": image_url,
                "thumbnail_url": thumbnail_url,
                "source_url": safe_source,
                "source": item.get("source", ""),
                "width": dims.get("width"),
                "height": dims.get("height"),
            }
        )
        if len(normalized_results) >= count:
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
