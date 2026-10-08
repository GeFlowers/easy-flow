'''提供网页抓取工具，并将项目配置转换为 Crawl4AI 客户端参数。'''

import logging

from langchain.tools import tool

from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config

from .crawl4ai_client import Crawl4AiClient

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11235"
DEFAULT_TIMEOUT_S = 30
DEFAULT_FILTER = "fit"
VALID_FILTERS = ("fit", "raw", "bm25", "llm")


def _get_tool_config(tool_name: str) -> dict | None:
    '''读取指定工具配置中的扩展字段；未配置时返回 ``None``。'''
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        return None
    extras = config.model_extra
    return extras if extras is not None else {}


def _coerce_timeout(value: object, default: int) -> float:
    '''将配置值转换为秒数；布尔值、非法字符串和其他类型均回退到默认值。'''
    if isinstance(value, bool):
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            logger.warning("Crawl4AI web_fetch: invalid timeout %r in config; using %ss", value, default)
    return float(default)


def _coerce_bool(value: object, default: bool) -> bool:
    '''将布尔值或常见真假字符串规范化；无法识别时使用默认值。'''
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_filter(value: object) -> str:
    '''校验并规范化正文筛选模式；未知值记录警告并回退到默认模式。'''
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_FILTERS:
            return normalized
        logger.warning("Crawl4AI web_fetch: unknown filter %r in config; using %r (valid: %s)", value, DEFAULT_FILTER, ", ".join(VALID_FILTERS))
    return DEFAULT_FILTER


def _build_client(cfg: dict | None) -> Crawl4AiClient:
    '''根据已读取的网页抓取配置创建客户端，避免重复读取热重载配置。'''
    base_url = DEFAULT_BASE_URL
    token = ""
    timeout_s: float = float(DEFAULT_TIMEOUT_S)
    if cfg is not None:
        base_url = cfg.get("base_url", base_url)
        token = cfg.get("token", token)
        timeout_s = _coerce_timeout(cfg.get("timeout"), DEFAULT_TIMEOUT_S)
    return Crawl4AiClient(base_url=base_url, token=token, timeout_s=timeout_s)


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    '''读取用户或搜索结果明确提供的网址，并返回网页正文。

    仅抓取完整网址，不补写 ``www``。无法访问需要登录的私有页面；网址必须包含
    ``http://`` 或 ``https://`` 协议头。

    Args:
        url: 要读取正文的完整网页地址。
    '''
    try:
        cfg = _get_tool_config("web_fetch")
        allow_private_addresses = _coerce_bool(cfg.get("allow_private_addresses") if cfg is not None else None, False)
        url_error = validate_public_http_url(url, allow_private_addresses=allow_private_addresses)
        if url_error:
            return url_error
        filter_mode = _coerce_filter(cfg.get("filter") if cfg is not None else None)
        client = _build_client(cfg)
        markdown = await client.fetch_markdown(url, filter_mode=filter_mode)

        if markdown.startswith("Error:"):
            return markdown

        return markdown[:4096]

    except Exception as e:
        logger.error(f"Error in web_fetch_tool: {e}")
        return f"Error: {str(e)}"
