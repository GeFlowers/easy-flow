"""提供配置、skill、扫描、配置相关功能。"""

from pydantic import BaseModel, Field


class SkillScanConfig(BaseModel):
    """\u6267\u884c SkillScanConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(
        default=True,
        description="Whether native deterministic SkillScan analyzers run before the LLM skill scanner.",
    )
