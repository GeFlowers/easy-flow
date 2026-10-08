'''配置用户消息发送前的输入润色模型、提示词和长度限制。'''

from pydantic import BaseModel, Field


class InputPolishConfig(BaseModel):
    '''为网关输入润色端点提供运行参数与模型覆盖设置。'''

    enabled: bool = Field(default=True, description="Whether to enable pre-send input polishing in the composer")
    max_chars: int = Field(default=4000, ge=1, description="Maximum number of draft characters accepted by the input polishing endpoint")
    model_name: str | None = Field(default=None, description="Optional model name override for input polishing")
