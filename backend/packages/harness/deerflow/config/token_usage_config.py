"""提供配置、token、usage、配置相关功能。"""
from pydantic import BaseModel, Field


class TokenUsageConfig(BaseModel):
    """\u6267\u884c TokenUsageConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(default=True, description="Enable token usage tracking middleware")
