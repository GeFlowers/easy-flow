'''控制运行期间的模型令牌用量统计中间件。'''

from pydantic import BaseModel, Field


class TokenUsageConfig(BaseModel):
    '''指定是否收集并附加每次运行的令牌用量数据。'''

    enabled: bool = Field(default=True, description="Enable token usage tracking middleware")
