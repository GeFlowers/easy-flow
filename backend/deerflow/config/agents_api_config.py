'''定义是否向网关开放自定义智能体提示文件管理接口的配置。'''

from pydantic import BaseModel, Field


class AgentsApiConfig(BaseModel):
    '''控制自定义智能体的提示文件读写路由是否启用。'''

    enabled: bool = Field(
        default=False,
        description=("Whether to expose the custom-agent management API over HTTP. When disabled, the gateway rejects read/write access to custom agent SOUL.md, config, and USER.md prompt-management routes."),
    )


_agents_api_config: AgentsApiConfig = AgentsApiConfig()


def get_agents_api_config() -> AgentsApiConfig:
    '''返回当前进程使用的自定义智能体接口配置。'''
    return _agents_api_config


def set_agents_api_config(config: AgentsApiConfig) -> None:
    '''替换当前进程中的自定义智能体接口配置。'''
    global _agents_api_config
    _agents_api_config = config


def load_agents_api_config_from_dict(config_dict: dict) -> None:
    '''用应用配置文件中的字段构造并缓存接口配置模型。'''
    global _agents_api_config
    _agents_api_config = AgentsApiConfig(**config_dict)
