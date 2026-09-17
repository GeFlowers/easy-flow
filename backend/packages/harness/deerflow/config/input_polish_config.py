"""提供配置、input、polish、配置相关功能。"""

from pydantic import BaseModel, Field


class InputPolishConfig(BaseModel):
    """\u6267\u884c InputPolishConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(default=True, description="Whether to enable pre-send input polishing in the composer")
    max_chars: int = Field(default=4000, ge=1, description="Maximum number of draft characters accepted by the input polishing endpoint")
    model_name: str | None = Field(default=None, description="Optional model name override for input polishing")
