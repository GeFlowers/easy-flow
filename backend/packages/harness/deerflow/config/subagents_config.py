'''定义内置与自定义子代理的超时、模型、技能和令牌预算覆盖。'''

import logging

from pydantic import BaseModel, Field

from deerflow.config.token_budget_config import TokenBudgetConfig

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN = 6
MIN_TOTAL_SUBAGENTS_PER_RUN = 1
MAX_TOTAL_SUBAGENTS_PER_RUN = 50
MIN_CONCURRENT_SUBAGENT_CALLS = 2
MAX_CONCURRENT_SUBAGENT_CALLS = 4


def clamp_subagent_concurrency(value: int) -> int:
    '''把并发子代理调用数限制在运行器支持的范围内。'''
    return max(MIN_CONCURRENT_SUBAGENT_CALLS, min(MAX_CONCURRENT_SUBAGENT_CALLS, value))


def clamp_total_subagents_per_run(value: int) -> int:
    '''限制单次主代理运行可累计分派的子代理总数。'''
    return max(MIN_TOTAL_SUBAGENTS_PER_RUN, min(MAX_TOTAL_SUBAGENTS_PER_RUN, value))


def default_subagent_token_budget(*, summarization_enabled: bool = False) -> TokenBudgetConfig:
    '''按是否启用摘要选择内置子代理的默认令牌预算。'''
    max_tokens = 1_000_000 if summarization_enabled else 2_000_000
    return TokenBudgetConfig(enabled=True, max_tokens=max_tokens, warn_threshold=0.7)


class SubagentOverrideConfig(BaseModel):
    '''保存对单个内置子代理生效的可选覆盖项。'''

    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Timeout in seconds for this subagent (None = use global default)",
    )
    max_turns: int | None = Field(
        default=None,
        ge=1,
        description="Maximum turns for this subagent (None = use global or builtin default)",
    )
    model: str | None = Field(
        default=None,
        min_length=1,
        description="Model name for this subagent (None = inherit from parent agent)",
    )
    skills: list[str] | None = Field(
        default=None,
        description="Skill names whitelist for this subagent (None = inherit all enabled skills, [] = no skills)",
    )
    token_budget: TokenBudgetConfig | None = Field(
        default=None,
        description="Per-run token budget override for this subagent (None = use the global subagents.token_budget default). Symmetric with timeout_seconds/max_turns.",
    )


class CustomSubagentConfig(BaseModel):
    '''声明自定义子代理的提示词、工具/技能白名单和执行上限。'''

    description: str = Field(
        description="When the lead agent should delegate to this subagent",
    )
    system_prompt: str = Field(
        description="System prompt that guides the subagent's behavior",
    )
    tools: list[str] | None = Field(
        default=None,
        description="Tool names whitelist (None = inherit all tools from parent)",
    )
    disallowed_tools: list[str] | None = Field(
        default_factory=lambda: ["task", "ask_clarification", "present_files"],
        description="Tool names to deny",
    )
    skills: list[str] | None = Field(
        default=None,
        description="Skill names whitelist (None = inherit all enabled skills, [] = no skills)",
    )
    model: str = Field(
        default="inherit",
        description="Model to use - 'inherit' uses parent's model",
    )
    max_turns: int = Field(
        default=50,
        ge=1,
        description="Maximum number of agent turns before stopping",
    )
    timeout_seconds: int = Field(
        default=900,
        ge=1,
        description="Maximum execution time in seconds",
    )


class SubagentsAppConfig(BaseModel):
    '''汇总子代理全局默认值、逐代理覆盖和用户自定义代理定义。'''

    timeout_seconds: int = Field(
        default=1800,
        ge=1,
        description="Default timeout in seconds for built-in subagents (default: 1800 = 30 minutes); custom agents use their own timeout_seconds unless given a per-agent override",
    )
    max_turns: int | None = Field(
        default=None,
        ge=1,
        description="Optional default max-turn override for all subagents (None = keep builtin defaults)",
    )
    max_total_per_run: int = Field(
        default=DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN,
        ge=MIN_TOTAL_SUBAGENTS_PER_RUN,
        le=MAX_TOTAL_SUBAGENTS_PER_RUN,
        description="Default total number of subagent delegations allowed in one lead-agent run. This is a deterministic backstop against repeated legal-sized task batches. Valid range: 1-50.",
    )
    token_budget: TokenBudgetConfig = Field(
        default_factory=default_subagent_token_budget,
        description="Default per-run token budget for subagents — a cost-ceiling backstop that engages by default (#3875 Phase 2). Set enabled: false to disable, or override per agent via agents.<name>.token_budget.",
    )
    agents: dict[str, SubagentOverrideConfig] = Field(
        default_factory=dict,
        description="Per-agent configuration overrides keyed by agent name",
    )
    custom_agents: dict[str, CustomSubagentConfig] = Field(
        default_factory=dict,
        description="User-defined subagent types keyed by agent name",
    )
    _token_budget_is_default: bool = True

    def __init__(self, **data):
        '''记录令牌预算是否来自默认值，以便摘要模式变化时重新计算默认预算。'''
        super().__init__(**data)
        self._token_budget_is_default = "token_budget" not in self.model_fields_set

    def get_timeout_for(self, agent_name: str) -> int:
        '''返回该子代理的专属超时；没有覆盖时采用全局默认值。'''
        override = self.agents.get(agent_name)
        if override is not None and override.timeout_seconds is not None:
            return override.timeout_seconds
        return self.timeout_seconds

    def get_model_for(self, agent_name: str) -> str | None:
        '''返回该子代理指定的模型，未设置时让调用方继承主代理模型。'''
        override = self.agents.get(agent_name)
        if override is not None and override.model is not None:
            return override.model
        return None

    def get_max_turns_for(self, agent_name: str, builtin_default: int) -> int:
        '''按逐代理覆盖、全局覆盖、内置代理默认值的顺序确定轮数上限。'''
        override = self.agents.get(agent_name)
        if override is not None and override.max_turns is not None:
            return override.max_turns
        if self.max_turns is not None:
            return self.max_turns
        return builtin_default

    def get_skills_for(self, agent_name: str) -> list[str] | None:
        '''返回逐代理技能白名单；未设置时由调用方继承全局可用技能。'''
        override = self.agents.get(agent_name)
        if override is not None and override.skills is not None:
            return override.skills
        return None

    def get_token_budget_for(
        self,
        agent_name: str,
        *,
        summarization_enabled: bool = False,
    ) -> TokenBudgetConfig:
        '''返回逐代理预算或全局预算，并在预算仍为默认值时按摘要状态重算。'''
        override = self.agents.get(agent_name)
        if override is not None and override.token_budget is not None:
            return override.token_budget
        if self._token_budget_is_default:
            return default_subagent_token_budget(summarization_enabled=summarization_enabled)
        return self.token_budget


_subagents_config: SubagentsAppConfig = SubagentsAppConfig()


def get_subagents_app_config() -> SubagentsAppConfig:
    '''返回当前进程使用的子代理配置。'''
    return _subagents_config


def load_subagents_config_from_dict(config_dict: dict) -> None:
    '''装载子代理配置，并记录生效覆盖项以便排查运行设置。'''
    global _subagents_config
    tb = config_dict.get("token_budget")
    if tb is not None and tb == default_subagent_token_budget(summarization_enabled=False).model_dump():
        config_dict = {k: v for k, v in config_dict.items() if k != "token_budget"}
    _subagents_config = SubagentsAppConfig(**config_dict)

    overrides_summary = {}
    for name, override in _subagents_config.agents.items():
        parts = []
        if override.timeout_seconds is not None:
            parts.append(f"timeout={override.timeout_seconds}s")
        if override.max_turns is not None:
            parts.append(f"max_turns={override.max_turns}")
        if override.model is not None:
            parts.append(f"model={override.model}")
        if override.skills is not None:
            parts.append(f"skills={override.skills}")
        if parts:
            overrides_summary[name] = ", ".join(parts)

    custom_agents_names = list(_subagents_config.custom_agents.keys())

    if overrides_summary or custom_agents_names:
        logger.info(
            "Subagents config loaded: default timeout=%ss, default max_turns=%s, per-agent overrides=%s, custom_agents=%s",
            _subagents_config.timeout_seconds,
            _subagents_config.max_turns,
            overrides_summary or "none",
            custom_agents_names or "none",
        )
