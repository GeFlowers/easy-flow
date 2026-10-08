'''定义工具组及工具提供者的配置格式，供应用装配阶段解析。'''

from pydantic import BaseModel, ConfigDict, Field


class ToolGroupConfig(BaseModel):
    '''标识一组相关工具，并允许工具组声明扩展属性。'''

    name: str = Field(..., description="Unique name for the tool group")
    model_config = ConfigDict(extra="allow")


class ToolConfig(BaseModel):
    '''将工具名称、所属分组和工厂导入路径绑定为一项配置。'''

    name: str = Field(..., description="Unique name for the tool")
    group: str = Field(..., description="Group name for the tool")
    use: str = Field(
        ...,
        description="Variable name of the tool provider(e.g. deerflow.sandbox.tools:bash_tool)",
    )
    model_config = ConfigDict(extra="allow")
