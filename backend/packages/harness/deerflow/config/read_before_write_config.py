'''配置沙箱写文件前是否要求读取目标内容及其适用工具范围。'''

from pydantic import BaseModel, Field


class ReadBeforeWriteConfig(BaseModel):
    '''定义读后写校验的启用状态、覆盖范围和豁免规则。'''

    enabled: bool = Field(
        default=True,
        description="Whether to block writes to existing files that were not read at their current version",
    )
