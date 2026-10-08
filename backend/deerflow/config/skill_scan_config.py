'''控制确定性技能扫描器是否在模型审核之前运行。'''

from pydantic import BaseModel, Field


class SkillScanConfig(BaseModel):
    '''保存技能包静态扫描阶段的启用状态。'''

    enabled: bool = Field(
        default=True,
        description="Whether native deterministic SkillScan analyzers run before the LLM skill scanner.",
    )
