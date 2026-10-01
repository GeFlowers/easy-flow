'''控制助手回复完成后是否生成后续问题建议。'''

from pydantic import BaseModel, Field


class SuggestionsConfig(BaseModel):
    '''为前端建议问题功能提供统一开关。'''

    enabled: bool = Field(default=True, description="Whether to enable follow-up question suggestions at the end of an AI response")
