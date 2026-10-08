'''从工具配置构造 Jina 客户端，并提取抓取结果中的正文。'''

import asyncio

from langchain.tools import tool

from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

readability_extractor = ReadabilityExtractor()


def _coerce_bool(value: object, default: bool) -> bool:
    '''解析布尔值或常见真假字符串；无法识别时返回默认值。'''
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_timeout(value: object, default: int) -> int:
    '''将超时配置转换为整数；布尔值、非法字符串和其他类型回退到默认值。'''
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _coerce_proxy(value: object) -> str | None:
    '''清理代理配置并返回非空地址；非字符串或空内容返回 ``None``。'''
    if not isinstance(value, str):
        return None
    proxy = value.strip()
    return proxy or None


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    '''读取指定网页的正文内容并返回给 agent。
    仅抓取用户直接提供或 web_search、web_fetch 工具结果中返回的完整原始网址。
    此工具无法访问需要身份验证的内容，例如私有 Google Docs 文档或需要登录的网页。
    不要给原本不含 www. 的网址添加该前缀。
    网址必须包含协议头：https://example.com 有效，而 example.com 无效。

    Args:
        url: 要读取内容的网页地址。
    '''
    jina_client = JinaClient()
    timeout = 10
    proxy = None
    trust_env = True
    config = get_app_config().get_tool_config("web_fetch")
    if config is not None:
        timeout = _coerce_timeout(config.model_extra.get("timeout"), timeout)
        proxy = _coerce_proxy(config.model_extra.get("proxy"))
        trust_env = _coerce_bool(config.model_extra.get("trust_env"), trust_env)
    html_content = await jina_client.crawl(url, return_format="html", timeout=timeout, proxy=proxy, trust_env=trust_env)
    if isinstance(html_content, str) and html_content.startswith("Error:"):
        return html_content
    article = await asyncio.to_thread(readability_extractor.extract_article, html_content)
    return article.to_markdown()[:4096]
