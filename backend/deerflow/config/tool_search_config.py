'''配置延迟加载工具模式及每次模型调用自动提升的工具数量。'''

from pydantic import BaseModel, Field, field_validator

AUTO_PROMOTE_TOP_K_MIN = 1
AUTO_PROMOTE_TOP_K_MAX = 5


def clamp_auto_promote_top_k(value: int) -> int:
    '''将自动提升工具数限制在支持的最小值与最大值之间。'''
    return max(AUTO_PROMOTE_TOP_K_MIN, min(AUTO_PROMOTE_TOP_K_MAX, int(value)))


class ToolSearchConfig(BaseModel):
    '''决定是否启用工具搜索，以及路由提示可自动恢复多少工具定义。'''

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
        '''在模型校验时规范自动提升数量，防止配置越界。'''
        return clamp_auto_promote_top_k(value)


_tool_search_config: ToolSearchConfig | None = None


def get_tool_search_config() -> ToolSearchConfig:
    '''返回进程内工具搜索配置，首次读取时创建默认值。'''
    global _tool_search_config
    if _tool_search_config is None:
        _tool_search_config = ToolSearchConfig()
    return _tool_search_config


def load_tool_search_config_from_dict(data: dict) -> ToolSearchConfig:
    '''校验字典并更新当前进程使用的工具搜索配置。'''
    global _tool_search_config
    _tool_search_config = ToolSearchConfig.model_validate(data)
    return _tool_search_config
