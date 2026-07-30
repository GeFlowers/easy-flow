"""提供配置、skill、evolution、配置相关功能。"""
from pydantic import BaseModel, Field


class SkillEvolutionConfig(BaseModel):
    """\u6267\u884c SkillEvolutionConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(
        default=False,
        description="Whether the agent can create and modify skills under skills/custom.",
    )
    moderation_model_name: str | None = Field(
        default=None,
        description="Optional model name for skill security moderation. Defaults to the primary chat model.",
    )
