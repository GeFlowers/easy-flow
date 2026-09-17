"定义 searxng_client 模块提供的职责与可复用接口"

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SearxngClient:
    """封装 SearxngClient 的状态、协作关系与公开操作。

    Client for SearXNG meta search engine API."""

    def __init__(self, base_url: str) -> None:
        "实现 __init__ 协议方法，保持对象交互语义一致"
        self.base_url = base_url.rstrip("/")

    async def search(
        self,
        query: str,
        max_results: int = 5,
        categories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """执行 search 的明确职责，并返回与调用约定一致的结果。

        Search the web using SearXNG.

                Args:
                    query: The search query.
                    max_results: Maximum number of results to return.
                    categories: Search categories to use.

                Returns:
                    List of search result dictionaries.
        """
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": "auto",
            "pageno": 1,
        }
        if max_results:
            params["limit"] = max_results
        if categories:
            params["categories"] = ",".join(categories)

        logger.debug(f"Searching SearXNG at {self.base_url} with query: {query}")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base_url}/search",
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; DeerFlow/1.0)",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                return results[:max_results] if max_results else results
        except httpx.HTTPStatusError as e:
            logger.error(f"SearXNG search returned error status: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"SearXNG search request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred during SearXNG search: {e}")
            raise
