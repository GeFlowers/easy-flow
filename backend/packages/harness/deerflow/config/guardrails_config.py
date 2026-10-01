'''定义安全护栏提供者及其启用、失败处理和初始化参数。'''

from pydantic import BaseModel, Field


class GuardrailProviderConfig(BaseModel):
    '''指定负责判定工具调用是否允许的护栏实现。'''

    use: str = Field(description="Class path (e.g. 'deerflow.guardrails.builtin:AllowlistProvider')")
    config: dict = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


class GuardrailsConfig(BaseModel):
    '''控制工具调用前的护栏检查及提供者故障时的默认策略。'''

    enabled: bool = Field(default=False, description="Enable guardrail middleware")
    fail_closed: bool = Field(default=True, description="Block tool calls if provider errors")
    passport: str | None = Field(default=None, description="OAP passport path or hosted agent ID")
    provider: GuardrailProviderConfig | None = Field(default=None, description="Guardrail provider configuration")


_guardrails_config: GuardrailsConfig | None = None


def get_guardrails_config() -> GuardrailsConfig:
    '''返回已缓存的护栏配置，未设置时创建默认实例。'''
    global _guardrails_config
    if _guardrails_config is None:
        _guardrails_config = GuardrailsConfig()
    return _guardrails_config


def load_guardrails_config_from_dict(data: dict) -> GuardrailsConfig:
    '''校验应用配置字段并替换当前护栏配置。'''
    global _guardrails_config
    _guardrails_config = GuardrailsConfig.model_validate(data)
    return _guardrails_config


def reset_guardrails_config() -> None:
    '''清除护栏配置缓存，供测试或配置重载使用。'''
    global _guardrails_config
    _guardrails_config = None
