'''通过 DuckDuckGo 搜索图片，并将结果整理为图像生成可使用的视觉参考。'''

import json
import logging

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)


def _search_images(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
    safesearch: str = "moderate",
    size: str | None = None,
    color: str | None = None,
    type_image: str | None = None,
    layout: str | None = None,
    license_image: str | None = None,
) -> list[dict]:
    '''按地区、安全级别和图片属性调用图片搜索服务，依赖缺失或请求失败时返回空列表。'''
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("ddgs library not installed. Run: pip install ddgs")
        return []

    ddgs = DDGS(timeout=30)

    try:
        kwargs = {
            "region": region,
            "safesearch": safesearch,
            "max_results": max_results,
        }

        if size:
            kwargs["size"] = size
        if color:
            kwargs["color"] = color
        if type_image:
            kwargs["type_image"] = type_image
        if layout:
            kwargs["layout"] = layout
        if license_image:
            kwargs["license_image"] = license_image

        results = ddgs.images(query, **kwargs)
        return list(results) if results else []

    except Exception as e:
        logger.error(f"Failed to search images: {e}")
        return []


@tool("image_search", parse_docstring=True)
def image_search_tool(
    query: str,
    max_results: int = 5,
    size: str | None = None,
    type_image: str | None = None,
    layout: str | None = None,
) -> str:
    '''在线搜索人物、物品或场景图片，为图像创作提供可核对的视觉参考。

    **适用场景：**
    - 生成人物或肖像前：搜索相似的姿势、表情和风格。
    - 生成具体物品或产品前：搜索准确的视觉参考。
    - 生成场景或地点前：搜索建筑或环境参考。
    - 生成时尚或服装图片前：搜索款式和细节参考。

    返回的图片地址可作为图像生成的参考素材，以明显改善生成质量。

    Args:
        query: 描述所需图片的关键词；尽量具体以提高结果相关性，例如使用“20 世纪 90 年代日本女性街头摄影”，而非仅使用“女性”。
        max_results: 返回图片的最大数量，默认值为 5。
        size: 图片尺寸筛选，可选值为 "Small"、"Medium"、"Large"、"Wallpaper"；参考图片建议使用 "Large"。
        type_image: 图片类型筛选，可选值为 "photo"、"clipart"、"gif"、"transparent"、"line"；写实参考建议使用 "photo"。
        layout: 布局筛选，可选值为 "Square"、"Tall"、"Wide"，按生成需求选择。
    '''
    config = get_app_config().get_tool_config("image_search")

    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", max_results)

    results = _search_images(
        query=query,
        max_results=max_results,
        size=size,
        type_image=type_image,
        layout=layout,
    )

    if not results:
        return json.dumps({"error": "No images found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "image_url": r.get("image", ""),
            "thumbnail_url": r.get("thumbnail", ""),
        }
        for r in results
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
        "usage_hint": "Use the 'image_url' values as reference images in image generation. Download them first if needed.",
    }

    return json.dumps(output, indent=2, ensure_ascii=False)
