'定义 tools 模块提供的职责与可复用接口'
from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

from .infoquest_client import InfoQuestClient

readability_extractor = ReadabilityExtractor()


def _get_infoquest_client() -> InfoQuestClient:
    '执行 _get_infoquest_client 的明确职责，并返回与调用约定一致的结果'
    search_config = get_app_config().get_tool_config("web_search")
    search_time_range = -1
    if search_config is not None and "search_time_range" in search_config.model_extra:
        search_time_range = search_config.model_extra.get("search_time_range")

    fetch_config = get_app_config().get_tool_config("web_fetch")
    fetch_time = -1
    if fetch_config is not None and "fetch_time" in fetch_config.model_extra:
        fetch_time = fetch_config.model_extra.get("fetch_time")
    fetch_timeout = -1
    if fetch_config is not None and "timeout" in fetch_config.model_extra:
        fetch_timeout = fetch_config.model_extra.get("timeout")
    navigation_timeout = -1
    if fetch_config is not None and "navigation_timeout" in fetch_config.model_extra:
        navigation_timeout = fetch_config.model_extra.get("navigation_timeout")

    image_search_config = get_app_config().get_tool_config("image_search")
    image_search_time_range = -1
    if image_search_config is not None and "image_search_time_range" in image_search_config.model_extra:
        image_search_time_range = image_search_config.model_extra.get("image_search_time_range")
    image_size = "i"
    if image_search_config is not None and "image_size" in image_search_config.model_extra:
        image_size = image_search_config.model_extra.get("image_size")

    return InfoQuestClient(
        search_time_range=search_time_range,
        fetch_timeout=fetch_timeout,
        fetch_navigation_timeout=navigation_timeout,
        fetch_time=fetch_time,
        image_search_time_range=image_search_time_range,
        image_size=image_size,
    )


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    '执行 web_search_tool 的明确职责，并返回与调用约定一致的结果。\n\nSearch the web.\n\n    Args:\n        query: The query to search for.\n    '

    client = _get_infoquest_client()
    return client.web_search(query)


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    '执行 web_fetch_tool 的明确职责，并返回与调用约定一致的结果。\n\nFetch the contents of a web page at a given URL.\n    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.\n    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.\n    Do NOT add www. to URLs that do NOT have them.\n    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.\n\n    Args:\n        url: The URL to fetch the contents of.\n    '
    client = _get_infoquest_client()
    result = client.fetch(url)
    if result.startswith("Error: "):
        return result
    article = readability_extractor.extract_article(result)
    return article.to_markdown()[:4096]


@tool("image_search", parse_docstring=True)
def image_search_tool(query: str) -> str:
    '执行 image_search_tool 的明确职责，并返回与调用约定一致的结果。\n\nSearch for images online. Use this tool BEFORE image generation to find reference images for characters, portraits, objects, scenes, or any content requiring visual accuracy.\n\n    **When to use:**\n    - Before generating character/portrait images: search for similar poses, expressions, styles\n    - Before generating specific objects/products: search for accurate visual references\n    - Before generating scenes/locations: search for architectural or environmental references\n    - Before generating fashion/clothing: search for style and detail references\n\n    The returned image URLs can be used as reference images in image generation to significantly improve quality.\n\n    Args:\n        query: The query to search for images.\n    '
    client = _get_infoquest_client()
    return client.image_search(query)
