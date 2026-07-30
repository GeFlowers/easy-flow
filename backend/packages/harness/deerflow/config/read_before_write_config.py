"""提供配置、read、before、write、配置相关功能。"""

from pydantic import BaseModel, Field


class ReadBeforeWriteConfig(BaseModel):
    """\u6267\u884c ReadBeforeWriteConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(
        default=True,
        description="Whether to block writes to existing files that were not read at their current version",
    )
