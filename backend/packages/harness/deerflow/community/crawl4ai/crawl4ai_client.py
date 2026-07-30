'定义 crawl4ai_client 模块提供的职责与可复用接口'
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class Crawl4AiClient:
    '封装 Crawl4AiClient 的状态、协作关系与公开操作。\n\nClient for a self-hosted Crawl4AI Docker server (POST /md).'

    def __init__(self, base_url: str, token: str = "", timeout_s: float = 30.0) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    async def fetch_markdown(self, url: str, filter_mode: str = "fit") -> str:
        '执行 fetch_markdown 的明确职责，并返回与调用约定一致的结果。\n\nFetch a page\'s clean markdown via Crawl4AI\'s POST /md endpoint.\n\n        Args:\n            url: The URL to fetch.\n            filter_mode: Crawl4AI markdown filter ("fit", "raw", "bm25", "llm").\n\n        Returns:\n            Markdown content, or an "Error: ..." string on failure.\n        '
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
                    return f"Error: Crawl4AI returned a non-JSON 200 response (content-type: {content_type}): {resp.text[:200]}"

                if not data.get("success", False):
                    return f"Error: Crawl4AI reported failure for {url}"

                markdown = data.get("markdown") or ""
                if not markdown.strip():
                    return "Error: Crawl4AI returned empty markdown"

                return markdown

        except httpx.TimeoutException:
            return f"Error: Crawl4AI request timed out after {self.timeout_s}s"
        except httpx.RequestError as e:
            logger.error(f"Crawl4AI request failed: {e}")
            return f"Error: Crawl4AI request failed: {e!s}"
        except Exception as e:
            logger.error(f"Crawl4AI fetch failed: {e}")
            return f"Error: Crawl4AI fetch failed: {e!s}"
