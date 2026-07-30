"""提供配置、agents、接口、配置相关功能。"""

from pydantic import BaseModel, Field


class AgentsApiConfig(BaseModel):
    """\u6267\u884c AgentsApiConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(
        default=False,
        description=("Whether to expose the custom-agent management API over HTTP. When disabled, the gateway rejects read/write access to custom agent SOUL.md, config, and USER.md prompt-management routes."),
    )


_agents_api_config: AgentsApiConfig = AgentsApiConfig()


def get_agents_api_config() -> AgentsApiConfig:
    """\u6267\u884c get_agents_api_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return _agents_api_config


def set_agents_api_config(config: AgentsApiConfig) -> None:
    """\u6267\u884c set_agents_api_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _agents_api_config
    _agents_api_config = config


def load_agents_api_config_from_dict(config_dict: dict) -> None:
    """\u6267\u884c load_agents_api_config_from_dict \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _agents_api_config
    _agents_api_config = AgentsApiConfig(**config_dict)
