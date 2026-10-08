'''设置单次智能体运行的总令牌预算、分项上限和警告/停止阈值。'''

from pydantic import BaseModel, Field, model_validator


class TokenBudgetConfig(BaseModel):
    '''为运行期预算中间件声明强制上限和软警告边界。'''

    enabled: bool = Field(default=False, description="Whether to enable per-run token budget enforcement.")
    max_tokens: int = Field(default=200000, ge=1000, description="Maximum total tokens (input + output) allowed per run.")
    max_input_tokens: int | None = Field(default=None, ge=1, description="Optional separate limit for input tokens only.")
    max_output_tokens: int | None = Field(default=None, ge=1, description="Optional separate limit for output tokens only.")
    warn_threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="Fraction of max_tokens at which a soft warning is injected. E.g., 0.8 means warn at 80% of max_tokens")
    hard_stop_threshold: float = Field(default=1.0, ge=0.0, le=1.0, description=("Fraction of max_tokens at which tool calls are stripped and the agent is forced to produce a final answer. E.g., 1.0 means stop at 100% of max_tokens."))

    @model_validator(mode="after")
    def validate_thresholds(self) -> "TokenBudgetConfig":
        '''保证强制停止阈值不低于警告阈值，避免配置顺序颠倒。'''
        if self.hard_stop_threshold < self.warn_threshold:
            raise ValueError("hard_stop_threshold must be >= warn_threshold")
        return self
