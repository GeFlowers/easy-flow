"""提供配置、title、配置相关功能。"""

from pydantic import BaseModel, Field


class TitleConfig(BaseModel):
    """\u6267\u884c TitleConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(
        default=True,
        description="Whether to enable automatic title generation",
    )
    max_words: int = Field(
        default=6,
        ge=1,
        le=20,
        description="Maximum number of words in the generated title",
    )
    max_chars: int = Field(
        default=60,
        ge=10,
        le=200,
        description="Maximum number of characters in the generated title",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for LLM title generation (None = use local fallback title)",
    )
    prompt_template: str = Field(
        default=("Generate a concise title (max {max_words} words) for this conversation.\nUser: {user_msg}\nAssistant: {assistant_msg}\n\nReturn ONLY the title, no quotes, no explanation."),
        description="Prompt template for LLM title generation when model_name is set",
    )
_title_config: TitleConfig = TitleConfig()


def get_title_config() -> TitleConfig:
    """\u6267\u884c get_title_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return _title_config


def set_title_config(config: TitleConfig) -> None:
    """\u6267\u884c set_title_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _title_config
    _title_config = config


def load_title_config_from_dict(config_dict: dict) -> None:
    """\u6267\u884c load_title_config_from_dict \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _title_config
    _title_config = TitleConfig(**config_dict)


def reset_title_config() -> None:
    """\u6267\u884c reset_title_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _title_config
    _title_config = TitleConfig()
