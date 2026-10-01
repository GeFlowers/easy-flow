'''定义从项目配置加载的 ACP（Agent Client Protocol，智能体客户端协议）智能体启动参数。'''

import logging
from collections.abc import Mapping

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ACPAgentConfig(BaseModel):
    '''描述单个兼容 ACP 协议的外部智能体及其启动和授权选项。'''

    command: str = Field(description="Command to launch the ACP agent subprocess")
    args: list[str] = Field(default_factory=list, description="Additional command arguments")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables to inject into the agent subprocess. Values starting with $ are resolved from host environment variables.")
    description: str = Field(description="Description of the agent's capabilities (shown in tool description)")
    model: str | None = Field(default=None, description="Model hint passed to the agent (optional)")
    auto_approve_permissions: bool = Field(
        default=False,
        description=(
            "When True, DeerFlow automatically approves all ACP permission requests from this agent "
            "(allow_once preferred over allow_always). When False (default), all permission requests "
            "are denied — the agent must be configured to operate without requesting permissions."
        ),
    )


_acp_agents: dict[str, ACPAgentConfig] = {}


def get_acp_agents() -> dict[str, ACPAgentConfig]:
    '''返回当前已加载的 ACP agent 配置表。

        Returns:
            按 agent 名称索引配置；未配置时返回空字典。
    '''
    return _acp_agents


def load_acp_config_from_dict(config_dict: Mapping[str, Mapping[str, object]] | None) -> None:
    '''用新字典替换当前 ACP agent 配置，通常由应用配置加载器调用。

        Args:
            config_dict: 按 agent 名称索引的字段映射；传入 None 时清空配置。
    '''
    global _acp_agents
    if config_dict is None:
        config_dict = {}
    _acp_agents = {name: ACPAgentConfig(**cfg) for name, cfg in config_dict.items()}
    logger.info("ACP config loaded: %d agent(s): %s", len(_acp_agents), list(_acp_agents.keys()))
