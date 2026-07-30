"""提供配置、suggestions、配置相关功能。"""
from pydantic import BaseModel, Field


class SuggestionsConfig(BaseModel):
    """\u6267\u884c SuggestionsConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(default=True, description="Whether to enable follow-up question suggestions at the end of an AI response")
