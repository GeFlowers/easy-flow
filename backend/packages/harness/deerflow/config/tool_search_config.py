"""提供配置、tool、搜索、配置相关功能。"""

from pydantic import BaseModel, Field, field_validator

AUTO_PROMOTE_TOP_K_MIN = 1
AUTO_PROMOTE_TOP_K_MAX = 5


def clamp_auto_promote_top_k(value: int) -> int:
    """\u6267\u884c clamp_auto_promote_top_k \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return max(AUTO_PROMOTE_TOP_K_MIN, min(AUTO_PROMOTE_TOP_K_MAX, int(value)))


class ToolSearchConfig(BaseModel):
    """\u6267\u884c ToolSearchConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(
        default=False,
        description="Defer tools and enable tool_search",
    )
    auto_promote_top_k: int = Field(
        default=3,
        description="Maximum number of deferred MCP tool schemas auto-promoted from routing metadata per model call",
    )

    @field_validator("auto_promote_top_k")
    @classmethod
    def _clamp_auto_promote_top_k(cls, value: int) -> int:
        """\u6267\u884c _clamp_auto_promote_top_k \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return clamp_auto_promote_top_k(value)


_tool_search_config: ToolSearchConfig | None = None


def get_tool_search_config() -> ToolSearchConfig:
    """\u6267\u884c get_tool_search_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _tool_search_config
    if _tool_search_config is None:
        _tool_search_config = ToolSearchConfig()
    return _tool_search_config


def load_tool_search_config_from_dict(data: dict) -> ToolSearchConfig:
    """\u6267\u884c load_tool_search_config_from_dict \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _tool_search_config
    _tool_search_config = ToolSearchConfig.model_validate(data)
    return _tool_search_config
