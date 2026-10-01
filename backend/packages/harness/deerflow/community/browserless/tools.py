'''实现基于 Browserless 的网页正文提取与网页截图工具，并把截图写入当前线程产物目录。'''

import asyncio
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.community.url_safety import resolve_host_addresses as _resolve_host_addresses
from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.tools.types import Runtime
from deerflow.utils.readability import ReadabilityExtractor

from .browserless_client import BrowserlessClient, BrowserlessScreenshotResult

logger = logging.getLogger(__name__)

_readability_extractor = ReadabilityExtractor()
_OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"
_OUTPUT_FORMAT_TO_EXTENSION = {
    "png": "png",
    "jpeg": "jpeg",
    "webp": "webp",
}
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_COLLISION_PROBES = 1000


def _get_tool_config(tool_name: str) -> dict | None:
    '''读取指定工具的扩展配置；工具未配置时返回 None，避免调用方重复处理配置对象。'''
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        return None
    extras = config.model_extra
    return extras if extras is not None else {}


def _get_browserless_client(tool_name: str = "web_fetch") -> BrowserlessClient:
    '''结合工具配置和环境变量创建 Browserless 客户端，并提供本地服务地址及超时默认值。'''
    cfg = _get_tool_config(tool_name)
    base_url = "http://localhost:3032"
    token = os.getenv("BROWSERLESS_TOKEN", "")
    timeout_s = 30.0
    if cfg is not None:
        base_url = cfg.get("base_url", base_url)
        token = cfg.get("token", token)
        raw = cfg.get("timeout_s", timeout_s)
        timeout_s = float(raw) if not isinstance(raw, float) else raw
    return BrowserlessClient(base_url=base_url, token=token, timeout_s=timeout_s)


def _as_bool(value: object, default: bool) -> bool:
    '''把布尔值或常见文本开关转换为布尔类型，遇到无法识别的输入时采用默认值。'''
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _as_int(value: object, default: int) -> int:
    '''把整数或数字文本转换为整数，拒绝布尔值并在解析失败时返回默认值。'''
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_optional_quality(value: object, output_format: str) -> int | None:
    '''仅为 JPEG 和 WebP 截图接受 0 到 100 的质量参数，其余情况不指定质量。'''
    if output_format not in {"jpeg", "webp"}:
        return None
    quality = _as_int(value, -1)
    return quality if 0 <= quality <= 100 else None


def _normalize_output_format(value: object) -> str:
    '''将截图格式限制为已支持的 PNG、JPEG 或 WebP，未知值回退到 PNG。'''
    output_format = str(value or "png").strip().lower()
    return output_format if output_format in _OUTPUT_FORMAT_TO_EXTENSION else "png"


def _validate_capture_url(url: str, allow_private_addresses: bool = False) -> str | None:
    '''校验截图目标网址是否为允许的 HTTP 地址，并按配置阻止访问私有网络地址。

    Validate a capture URL for scheme and (unless opted out) SSRF safety.

        Blocks requests that resolve to loopback, private, link-local (incl. the
        169.254.169.254 cloud-metadata endpoint), reserved, multicast, or
        unspecified addresses. Operators who intentionally point the tool at an
        internal Browserless target can opt out via ``allow_private_addresses``.
    '''
    return validate_public_http_url(
        url,
        allow_private_addresses=allow_private_addresses,
        action="capture",
        resolver=_resolve_host_addresses,
    )


def _default_capture_stem(url: str) -> str:
    '''从目标网址的主机和路径生成适合截图文件名使用的基础名称。'''
    parsed = urlparse(url)
    parts = [parsed.netloc, *[part for part in parsed.path.split("/") if part]]
    raw = "-".join(parts) or "web-capture"
    return raw[:80]


def _safe_capture_filename(filename: str | None, url: str, output_format: str) -> str:
    '''清除用户文件名中的目录和不安全字符，并统一替换为所选图片格式的扩展名。'''
    extension = _OUTPUT_FORMAT_TO_EXTENSION[output_format]
    if filename:
        raw_name = Path(filename).name
        stem = Path(raw_name).stem or "web-capture"
    else:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        stem = f"{_default_capture_stem(url)}-{timestamp}"

    safe_stem = _SAFE_FILENAME_RE.sub("_", stem).strip("._-") or "web-capture"
    return f"{safe_stem[:100]}.{extension}"


def _thread_outputs_path(runtime: Runtime) -> Path | str:
    '''从运行时线程状态取得产物目录；上下文缺失时返回可直接反馈给工具调用方的错误。'''
    if runtime.state is None:
        return "Error: Thread runtime state is not available"
    thread_data = runtime.state.get("thread_data") or {}
    outputs_path = thread_data.get("outputs_path")
    if not outputs_path:
        return "Error: Thread outputs path is not available"
    return Path(outputs_path)


def _tool_message(content: str, tool_call_id: str) -> Command:
    '''构造关联当前工具调用编号的消息更新命令。'''
    return Command(update={"messages": [ToolMessage(content, tool_call_id=tool_call_id)]})


def _dedupe_output_name(outputs_path: Path, output_name: str) -> str:
    '''为截图选择不会覆盖已有文件的名称，目录中重名时添加序号或时间戳。

    Return a non-colliding filename under ``outputs_path``.

        Keeps the original name when free, otherwise appends ``-1``, ``-2``, ...
        before the extension so an explicit filename never silently overwrites an
        earlier capture. Falls back to a timestamp suffix if the directory is
        saturated with the bounded probe range.
    '''
    candidate = outputs_path / output_name
    if not candidate.exists():
        return output_name

    stem = Path(output_name).stem
    suffix = Path(output_name).suffix
    for index in range(1, _MAX_FILENAME_COLLISION_PROBES + 1):
        probe = f"{stem}-{index}{suffix}"
        if not (outputs_path / probe).exists():
            return probe

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    return f"{stem}-{timestamp}{suffix}"


def _write_capture_output(outputs_path: Path, output_name: str, content: bytes) -> str:
    '''创建产物目录、以不冲突的名称写入截图字节，并返回实际使用的文件名。'''
    outputs_path.mkdir(parents=True, exist_ok=True)
    final_name = _dedupe_output_name(outputs_path, output_name)
    (outputs_path / final_name).write_bytes(content)
    return final_name


def _target_status_warning(result: BrowserlessScreenshotResult) -> str:
    '''根据被截图网页自身的响应状态生成提示，避免把浏览器服务成功误认为目标网页成功。

    Return a human-readable warning when the captured page itself errored.

        Browserless returns HTTP 200 for the render request even when the target
        page responded with a 4xx/5xx (or was an error/anti-bot page), so the raw
        image alone cannot be trusted as valid visual evidence. The target's real
        status is surfaced via the X-Response-Code header.
    '''
    code = result.target_status_code.strip()
    if not code or code.startswith(("2", "3")):
        return ""
    status = result.target_status.strip()
    detail = f"{code} {status}".strip()
    return f" (warning: target page responded {detail})"


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    '''通过 Browserless 浏览器读取指定网页内容，支持需要页面渲染的站点。
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    '''
    try:
        cfg = _get_tool_config("web_fetch") or {}
        allow_private_addresses = _as_bool(cfg.get("allow_private_addresses"), False)
        url_error = validate_public_http_url(
            url,
            allow_private_addresses=allow_private_addresses,
            resolver=_resolve_host_addresses,
        )
        if url_error:
            return url_error

        wait_for_event = ""
        wait_for_timeout_ms = 0
        wait_for_selector = ""
        wait_for_selector_timeout_ms = 5000
        reject_resource_types: list[str] | None = None
        reject_request_pattern: list[str] | None = None

        wait_for_event = cfg.get("wait_for_event", wait_for_event)
        raw_wait = cfg.get("wait_for_timeout_ms", wait_for_timeout_ms)
        wait_for_timeout_ms = int(raw_wait) if not isinstance(raw_wait, int) else raw_wait
        wait_for_selector = cfg.get("wait_for_selector", wait_for_selector)

        client = _get_browserless_client("web_fetch")
        html = await client.fetch_html(
            url=url,
            wait_for_event=wait_for_event,
            wait_for_timeout_ms=wait_for_timeout_ms,
            wait_for_selector=wait_for_selector,
            wait_for_selector_timeout_ms=wait_for_selector_timeout_ms,
            reject_resource_types=reject_resource_types,
            reject_request_pattern=reject_request_pattern,
        )

        if html.startswith("Error:"):
            return html

        article = await asyncio.to_thread(_readability_extractor.extract_article, html)
        return article.to_markdown()[:4096]

    except Exception as e:
        logger.error(f"Error in web_fetch_tool: {e}")
        return f"Error: {str(e)}"


@tool("web_capture", parse_docstring=True)
async def web_capture_tool(
    runtime: Runtime,
    url: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    filename: str | None = None,
    full_page: bool | None = None,
    output_format: str | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
) -> Command:
    '''截取渲染后的网页画面，并将截图作为项目产物呈现。

    Use this tool when you need a visual capture of a public webpage, especially JavaScript-heavy pages, UI states, dashboards, or visual evidence for a report.
    Only capture exact URLs provided by the user or discovered through other tools. Do not use this for private pages behind login unless the user has explicitly configured Browserless outside DeerFlow.
    URLs must include the schema: https://example.com is valid while example.com is invalid.

    Args:
        url: The http(s) URL to capture.
        filename: Optional output filename. Directories are ignored and the extension is determined by output_format.
        full_page: Optional override for full-page capture.
        output_format: Optional image format: png, jpeg, or webp.
        viewport_width: Optional viewport width in pixels.
        viewport_height: Optional viewport height in pixels.
    '''
    try:
        cfg = _get_tool_config("web_capture") or {}
        allow_private_addresses = _as_bool(cfg.get("allow_private_addresses"), False)

        url_error = _validate_capture_url(url, allow_private_addresses=allow_private_addresses)
        if url_error:
            return _tool_message(url_error, tool_call_id)

        outputs_path = _thread_outputs_path(runtime)
        if isinstance(outputs_path, str):
            return _tool_message(outputs_path, tool_call_id)

        final_format = _normalize_output_format(output_format or cfg.get("output_format", "png"))
        final_full_page = full_page if full_page is not None else _as_bool(cfg.get("full_page"), True)
        final_width = viewport_width if viewport_width is not None else _as_int(cfg.get("viewport_width"), 1280)
        final_height = viewport_height if viewport_height is not None else _as_int(cfg.get("viewport_height"), 720)
        quality = _as_optional_quality(cfg.get("quality"), final_format)
        wait_for_selector = str(cfg.get("wait_for_selector") or "")
        wait_for_selector_timeout_ms = _as_int(cfg.get("wait_for_selector_timeout_ms"), 5000)
        wait_for_timeout_ms = _as_int(cfg.get("wait_for_timeout_ms"), 0)
        best_attempt = _as_bool(cfg.get("best_attempt"), False)

        output_name = _safe_capture_filename(filename, url, final_format)

        client = _get_browserless_client("web_capture")
        result = await client.capture_screenshot(
            url=url,
            full_page=final_full_page,
            output_format=final_format,
            quality=quality,
            viewport={"width": final_width, "height": final_height},
            wait_for_selector=wait_for_selector,
            wait_for_selector_timeout_ms=wait_for_selector_timeout_ms,
            wait_for_timeout_ms=wait_for_timeout_ms,
            best_attempt=best_attempt,
        )
        if isinstance(result, str):
            return _tool_message(result, tool_call_id)

        final_name = await asyncio.to_thread(_write_capture_output, outputs_path, output_name, result.content)
        virtual_path = f"{_OUTPUTS_VIRTUAL_PREFIX}/{final_name}"
        message = f"Captured screenshot: {virtual_path}{_target_status_warning(result)}"
        return Command(
            update={
                "artifacts": [virtual_path],
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )

    except Exception as e:
        logger.error(f"Error in web_capture_tool: {e}")
        return _tool_message(f"Error: {str(e)}", tool_call_id)
