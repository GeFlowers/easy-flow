"""提供配置、安全护栏、配置相关功能。"""

from pydantic import BaseModel, Field


class GuardrailProviderConfig(BaseModel):
    """\u6267\u884c GuardrailProviderConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    use: str = Field(description="Class path (e.g. 'deerflow.guardrails.builtin:AllowlistProvider')")
    config: dict = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


class GuardrailsConfig(BaseModel):
    """\u6267\u884c GuardrailsConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(default=False, description="Enable guardrail middleware")
    fail_closed: bool = Field(default=True, description="Block tool calls if provider errors")
    passport: str | None = Field(default=None, description="OAP passport path or hosted agent ID")
    provider: GuardrailProviderConfig | None = Field(default=None, description="Guardrail provider configuration")


_guardrails_config: GuardrailsConfig | None = None


def get_guardrails_config() -> GuardrailsConfig:
    """\u6267\u884c get_guardrails_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _guardrails_config
    if _guardrails_config is None:
        _guardrails_config = GuardrailsConfig()
    return _guardrails_config


def load_guardrails_config_from_dict(data: dict) -> GuardrailsConfig:
    """\u6267\u884c load_guardrails_config_from_dict \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _guardrails_config
    _guardrails_config = GuardrailsConfig.model_validate(data)
    return _guardrails_config


def reset_guardrails_config() -> None:
    """\u6267\u884c reset_guardrails_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _guardrails_config
    _guardrails_config = None
