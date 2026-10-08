'''封装对无头浏览器服务的异步调用，用于获取渲染页面内容和网页截图。'''

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrowserlessScreenshotResult:
    '''保存截图字节、媒体类型、目标页面状态和最终访问地址。'''

    content: bytes
    content_type: str
    target_status_code: str
    target_status: str
    final_url: str


def _get_header(headers: Any, name: str) -> str:
    '''按大小写不敏感方式取得响应头，并统一返回字符串。'''
    value = headers.get(name)
    if value:
        return str(value)
    return str(headers.get(name.lower(), ""))


class BrowserlessClient:
    '''保存浏览器服务地址、可选访问令牌和每次请求的超时限制。'''

    def __init__(self, base_url: str, token: str = "", timeout_s: float = 30) -> None:
        '''去除服务地址尾部斜杠并保存连接参数，供页面内容和截图请求共用。'''
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    async def fetch_html(
        self,
        url: str,
        wait_for_event: str = "",
        wait_for_timeout_ms: int = 0,
        wait_for_selector: str = "",
        wait_for_selector_timeout_ms: int = 5000,
        reject_resource_types: list[str] | None = None,
        reject_request_pattern: list[str] | None = None,
    ) -> str:
        '''请求浏览器渲染指定网址，可配置等待事件、选择器和需拦截资源，并返回页面 HTML 或错误文本。'''
        payload: dict[str, Any] = {
            "url": url,
        }

        if self.token:
            payload["token"] = self.token
        if wait_for_event:
            payload["waitForEvent"] = wait_for_event
        if wait_for_timeout_ms > 0:
            payload["waitForTimeout"] = wait_for_timeout_ms
        if wait_for_selector:
            payload["waitForSelector"] = {
                "selector": wait_for_selector,
                "timeout": wait_for_selector_timeout_ms,
            }
        if reject_resource_types:
            payload["rejectResourceTypes"] = reject_resource_types
        if reject_request_pattern:
            payload["rejectRequestPattern"] = reject_request_pattern

        logger.debug(f"Fetching URL via Browserless: {url}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/content",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Cache-Control": "no-cache",
                    },
                )

                code = resp.status_code
                target_code = resp.headers.get("X-Response-Code", "")
                target_status = resp.headers.get("X-Response-Status", "")

                logger.debug(f"Browserless response: code={code}, target_code={target_code}, target_status={target_status}")

                if code != 200:
                    return f"Error: Browserless HTTP {code}: {resp.text[:200]}"

                html = resp.text
                if not html or not html.strip():
                    return "Error: Browserless returned empty response"

                return html

        except httpx.TimeoutException:
            return f"Error: Browserless request timed out after {self.timeout_s}s"
        except httpx.RequestError as e:
            logger.error(f"Browserless request failed: {e}")
            return f"Error: Browserless request failed: {e!s}"
        except Exception as e:
            logger.error(f"Browserless fetch failed: {e}")
            return f"Error: Browserless fetch failed: {e!s}"

    async def capture_screenshot(
        self,
        url: str,
        full_page: bool = True,
        output_format: str = "png",
        quality: int | None = None,
        viewport: dict[str, int] | None = None,
        wait_for_selector: str = "",
        wait_for_selector_timeout_ms: int = 5000,
        wait_for_timeout_ms: int = 0,
        best_attempt: bool = False,
    ) -> BrowserlessScreenshotResult | str:
        '''请求浏览器渲染并截取网页，按格式、视口和等待条件配置；返回截图及目标响应信息或错误文本。'''
        payload: dict[str, Any] = {
            "url": url,
            "options": {
                "fullPage": full_page,
                "type": output_format,
            },
        }
        if quality is not None:
            payload["options"]["quality"] = quality
        if viewport:
            payload["viewport"] = viewport
        if wait_for_selector:
            payload["waitForSelector"] = {
                "selector": wait_for_selector,
                "timeout": wait_for_selector_timeout_ms,
            }
        if wait_for_timeout_ms > 0:
            payload["waitForTimeout"] = wait_for_timeout_ms
        if best_attempt:
            payload["bestAttempt"] = True

        params = {"token": self.token} if self.token else None

        logger.debug(f"Capturing URL screenshot via Browserless: {url}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/screenshot",
                    json=payload,
                    params=params,
                    headers={
                        "Content-Type": "application/json",
                        "Cache-Control": "no-cache",
                    },
                )

                code = resp.status_code
                logger.debug(
                    "Browserless screenshot response: code=%s, target_code=%s, target_status=%s",
                    code,
                    resp.headers.get("X-Response-Code", ""),
                    resp.headers.get("X-Response-Status", ""),
                )

                if code != 200:
                    return f"Error: Browserless HTTP {code}: {resp.text[:200]}"

                content = resp.content
                if not content:
                    return "Error: Browserless returned empty screenshot response"

                return BrowserlessScreenshotResult(
                    content=content,
                    content_type=_get_header(resp.headers, "Content-Type"),
                    target_status_code=_get_header(resp.headers, "X-Response-Code"),
                    target_status=_get_header(resp.headers, "X-Response-Status"),
                    final_url=_get_header(resp.headers, "X-Response-URL"),
                )

        except httpx.TimeoutException:
            return f"Error: Browserless screenshot request timed out after {self.timeout_s}s"
        except httpx.RequestError as e:
            logger.error(f"Browserless screenshot request failed: {e}")
            return f"Error: Browserless screenshot request failed: {e!s}"
        except Exception as e:
            logger.error(f"Browserless screenshot failed: {e}")
            return f"Error: Browserless screenshot failed: {e!s}"
