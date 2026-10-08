'''通过 Firecrawl 兼容接口提供 FastCRW 搜索和网页抓取工具。'''

import json
import os

from firecrawl import FirecrawlApp
from langchain.tools import tool

from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config

# FastCRW 兼容 Firecrawl 接口，因此复用其客户端并允许替换服务地址；自托管地址
# 可通过工具配置中的 ``base_url`` 或环境变量 ``CRW_API_URL`` 指定。
DEFAULT_BASE_URL = "https://fastcrw.com/api"


def _get_fastcrw_client(tool_name: str = "web_search") -> FirecrawlApp:
    '''优先读取工具配置，再从环境变量获取凭据和服务地址并创建客户端。'''
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    base_url = None
    if config is not None:
        if "api_key" in config.model_extra:
            api_key = config.model_extra.get("api_key")
        if "base_url" in config.model_extra:
            base_url = config.model_extra.get("base_url")
    if api_key is None:
        api_key = os.getenv("CRW_API_KEY")
    if base_url is None:
        base_url = os.getenv("CRW_API_URL", DEFAULT_BASE_URL)
    return FirecrawlApp(api_key=api_key, api_url=base_url)  # type: ignore[arg-type]


def _get_tool_config_extra(tool_name: str) -> dict:
    '''返回指定工具的扩展配置副本；工具未配置时返回空字典。'''
    config = get_app_config().get_tool_config(tool_name)
    return dict(config.model_extra or {}) if config is not None else {}


def _coerce_bool(value: object, default: bool) -> bool:
    '''解析布尔值或常见真假字符串；无法识别时返回调用方给定的默认值。'''
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    '''搜索网络并返回与查询相关的资料。

    Args:
        query: 要检索的查询内容。
    '''
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = 5
        if config is not None:
            max_results = config.model_extra.get("max_results", max_results)

        client = _get_fastcrw_client("web_search")
        result = client.search(query, limit=max_results)

        # SDK 将网页搜索结果放在 result.web 字段中。
        web_results = result.web or []
        normalized_results = [
            {
                "title": getattr(item, "title", "") or "",
                "url": getattr(item, "url", "") or "",
                "snippet": getattr(item, "description", "") or "",
            }
            for item in web_results
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
        cfg = _get_tool_config_extra("web_fetch")
        allow_private_addresses = _coerce_bool(cfg.get("allow_private_addresses"), False)
        url_error = validate_public_http_url(url, allow_private_addresses=allow_private_addresses)
        if url_error:
            return url_error
        client = _get_fastcrw_client("web_fetch")
        result = client.scrape(url, formats=["markdown"])

        markdown_content = result.markdown or ""
        metadata = result.metadata
        title = metadata.title if metadata and metadata.title else "Untitled"

        if not markdown_content:
            return "Error: No content found"
    except Exception as e:
        return f"Error: {str(e)}"

    return f"# {title}\n\n{markdown_content[:4096]}"
