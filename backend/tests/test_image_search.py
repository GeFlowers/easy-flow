"""覆盖本文件测试的输入约束、模拟边界与回归保护，确保测试仅记录既有行为。"""

import json
from unittest.mock import MagicMock, patch

from deerflow.community.image_search.tools import image_search_tool


def test_image_search_uses_full_image_url_not_thumbnail():
    # 回归边界：下方用例固定不可信输入不得伪造受信任边界或权限上下文。
    # 此处说明下方测试的前置条件与预期，便于回归时定位断言所保护的行为边界。
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    fake_results = [
        {
            "title": "a cat",
            "image": "https://example.com/full.jpg",
            "thumbnail": "https://example.com/thumb.jpg",
        }
    ]
    cfg = MagicMock()
    cfg.get_tool_config.return_value = None

    with (
        patch("deerflow.community.image_search.tools._search_images", return_value=fake_results),
        patch("deerflow.community.image_search.tools.get_app_config", return_value=cfg),
    ):
        output = json.loads(image_search_tool.invoke({"query": "a cat"}))

    result = output["results"][0]
    assert result["image_url"] == "https://example.com/full.jpg"
    assert result["thumbnail_url"] == "https://example.com/thumb.jpg"
