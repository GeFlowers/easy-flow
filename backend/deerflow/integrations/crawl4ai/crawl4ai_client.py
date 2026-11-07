'''封装对自托管 Crawl4AI 服务的请求发送与响应校验。'''

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class Crawl4AiClient:
    '''保存抓取服务连接参数，并提供网页正文抓取操作。'''

    def __init__(self, base_url: str, token: str = "", timeout_s: float = 30.0) -> None:
        '''保存服务地址、可选访问令牌和请求超时时间。'''
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    async def fetch_markdown(self, url: str, filter_mode: str = "fit") -> str:
        '''请求正文接口，并返回 Markdown 内容或可读错误信息。

        Args:
            url: 要抓取的网页地址。
            filter_mode: 服务端支持的正文筛选模式。
        '''
        payload: dict[str, Any] = {"url": url, "f": filter_mode}
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        logger.debug(f"Fetching URL via Crawl4AI: {url}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(f"{self.base_url}/md", json=payload, headers=headers)

                if resp.status_code != 200:
                    return f"Error: Crawl4AI HTTP {resp.status_code}: {resp.text[:200]}"

                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError):
                    content_type = resp.headers.get("content-type", "unknown")
                    return f"Error: Crawl4AI 返回状态码 200，但内容不是 JSON（content-type: {content_type}）： {resp.text[:200]}"

                if not data.get("success", False):
                    return f"Error: Crawl4AI 报告抓取失败：{url}"

                markdown = data.get("markdown") or ""
                if not markdown.strip():
                    return "Error: Crawl4AI 返回空 Markdown 内容"

                return markdown

        except httpx.TimeoutException:
            return f"Error: Crawl4AI 请求超过 {self.timeout_s} 秒后超时"
        except httpx.RequestError as e:
            logger.error(f"Crawl4AI request failed: {e}")
            return f"Error: Crawl4AI 请求失败： {e!s}"
        except Exception as e:
            logger.error(f"Crawl4AI fetch failed: {e}")
            return f"Error: Crawl4AI 抓取失败： {e!s}"
