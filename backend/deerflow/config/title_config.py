'''配置对话标题生成开关、长度限制、模型选择和提示词模板。'''

from pydantic import BaseModel, Field


class TitleConfig(BaseModel):
    '''为标题生成器提供模型提示和本地回退标题的边界设置。'''

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
        default=("为本次对话生成简洁标题（最多 {max_words} 个词）。\n用户：{user_msg}\n助手：{assistant_msg}\n\n仅返回标题，不加引号，不作解释。"),
        description="Prompt template for LLM title generation when model_name is set",
    )
_title_config: TitleConfig = TitleConfig()


def get_title_config() -> TitleConfig:
    '''返回当前标题生成配置。'''
    return _title_config


def set_title_config(config: TitleConfig) -> None:
    '''替换当前标题生成配置，供应用启动配置阶段使用。'''
    global _title_config
    _title_config = config


def load_title_config_from_dict(config_dict: dict) -> None:
    '''从应用配置字典创建并缓存标题生成配置。'''
    global _title_config
    _title_config = TitleConfig(**config_dict)


def reset_title_config() -> None:
    '''恢复默认标题生成配置，主要供测试和重载流程使用。'''
    global _title_config
    _title_config = TitleConfig()
