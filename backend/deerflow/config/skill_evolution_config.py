'''控制智能体是否可创建或修改自定义技能，以及可选的审核模型。'''

from pydantic import BaseModel, Field


class SkillEvolutionConfig(BaseModel):
    '''为技能演化工具提供启用状态和安全审核模型设置。'''

    enabled: bool = Field(
        default=False,
        description="Whether the agent can create and modify skills under skills/custom.",
    )
    moderation_model_name: str | None = Field(
        default=None,
        description="Optional model name for skill security moderation. Defaults to the primary chat model.",
    )
