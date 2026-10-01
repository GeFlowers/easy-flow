'''定义上下文摘要触发阈值、摘要模型和摘要后保留的历史范围。'''

from typing import Literal

from pydantic import BaseModel, Field

ContextSizeType = Literal["fraction", "tokens", "messages"]
DEFAULT_SKILL_FILE_READ_TOOL_NAMES: tuple[str, ...] = ("read_file", "read", "view", "cat")


class ContextSize(BaseModel):
    '''以类型和值描述消息数、令牌数或上下文占比阈值。'''

    type: ContextSizeType = Field(description="Type of context size specification")
    value: int | float = Field(description="Value for the context size specification")

    def to_tuple(self) -> tuple[ContextSizeType, int | float]:
        '''将阈值模型转换为供摘要策略比较的二元组。'''
        return (self.type, self.value)


class SummarizationConfig(BaseModel):
    '''控制对话何时压缩上下文，以及压缩后保留多少近期内容。'''

    enabled: bool = Field(
        default=False,
        description="Whether to enable automatic conversation summarization",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for summarization (None = use a lightweight model)",
    )
    trigger: ContextSize | list[ContextSize] | None = Field(
        default=None,
        description="One or more thresholds that trigger summarization. When any threshold is met, summarization runs. "
        "Examples: {'type': 'messages', 'value': 50} triggers at 50 messages, "
        "{'type': 'tokens', 'value': 4000} triggers at 4000 tokens, "
        "{'type': 'fraction', 'value': 0.8} triggers at 80% of model's max input tokens",
    )
    keep: ContextSize = Field(
        default_factory=lambda: ContextSize(type="messages", value=20),
        description="Context retention policy after summarization. Specifies how much history to preserve. "
        "Examples: {'type': 'messages', 'value': 20} keeps 20 messages, "
        "{'type': 'tokens', 'value': 3000} keeps 3000 tokens, "
        "{'type': 'fraction', 'value': 0.3} keeps 30% of model's max input tokens",
    )
    trim_tokens_to_summarize: int | None = Field(
        default=4000,
        description="Maximum tokens to keep when preparing messages for summarization. Pass null to skip trimming.",
    )
    summary_prompt: str | None = Field(
        default=None,
        description="Custom prompt template for generating summaries. If not provided, uses the default LangChain prompt.",
    )
    skill_file_read_tool_names: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SKILL_FILE_READ_TOOL_NAMES),
        description="Tool names treated as skill-file reads when capturing loaded skills into the durable skill_context channel.",
    )
_summarization_config: SummarizationConfig = SummarizationConfig()


def get_summarization_config() -> SummarizationConfig:
    '''返回当前上下文摘要配置。'''
    return _summarization_config


def set_summarization_config(config: SummarizationConfig) -> None:
    '''替换当前上下文摘要配置。'''
    global _summarization_config
    _summarization_config = config


def load_summarization_config_from_dict(config_dict: dict) -> None:
    '''从应用配置字段校验并缓存摘要设置。'''
    global _summarization_config
    _summarization_config = SummarizationConfig(**config_dict)
