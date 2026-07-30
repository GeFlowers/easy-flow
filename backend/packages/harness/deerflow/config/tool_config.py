"""提供配置、tool、配置相关功能。"""
from pydantic import BaseModel, ConfigDict, Field


class ToolGroupConfig(BaseModel):
    """\u6267\u884c ToolGroupConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    name: str = Field(..., description="Unique name for the tool group")
    model_config = ConfigDict(extra="allow")


class ToolConfig(BaseModel):
    """\u6267\u884c ToolConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    name: str = Field(..., description="Unique name for the tool")
    group: str = Field(..., description="Group name for the tool")
    use: str = Field(
        ...,
        description="Variable name of the tool provider(e.g. deerflow.sandbox.tools:bash_tool)",
    )
    model_config = ConfigDict(extra="allow")
