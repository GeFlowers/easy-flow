'''自定义智能体的配置定义与加载功能。

自定义智能体按用户存储在 ``{base_dir}/users/{user_id}/agents/{name}/`` 下。
为兼容用户隔离功能之前的安装，仍可读取 ``{base_dir}/agents/{name}/`` 中的旧版
共享布局，作为只读回退保留。仓库不再提供旧布局自动迁移脚本，所有新写入始终
使用按用户划分的布局。
'''

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def _blank_to_none(value: str | None) -> str | None:
    '''将仅含空白字符的字符串规范化为 ``None``，其余有效值保持不变。

    仅含空白字符的字符串（例如 ``"   "``）在 Python 中为真值，因此未执行
    strip 的 ``value or fallback`` 表达式不会回退。``require_mention`` 的
    优先级链（``trigger.mention_login`` -> ``github.bot_login`` ->
    ``channels.github.default_mention_login`` -> ``agent.name``）依赖这一回退行为，
    故在模型层统一规范化这两个来自配置的环节。
    这样所有下游读取方（当前及未来）都会看到真实的“未设置”状态，而非永远无法
    匹配真实 ``@mention`` 的字面空白字符串。
    '''
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class GitHubTriggerConfig(BaseModel):
    '''GitHubBinding 内按事件生效的触发筛选器。'''

    actions: list[str] | None = None
    require_mention: bool = False
    allow_authors: list[str] = Field(default_factory=list)
    mention_login: str | None = None

    @field_validator("mention_login")
    @classmethod
    def _normalize_mention_login(cls, value: str | None) -> str | None:
        '''规范化提及登录名中的空白值。'''
        return _blank_to_none(value)


class GitHubBinding(BaseModel):
    '''一个带有按事件触发覆盖项的（智能体、仓库）绑定。'''

    repo: str
    triggers: dict[str, GitHubTriggerConfig] = Field(default_factory=dict)


class GitHubAgentConfig(BaseModel):
    '''自定义智能体 ``config.yaml`` 中顶层的 ``github:`` 配置块。'''

    installation_id: int | None = None
    bot_login: str | None = None
    recursion_limit: int | None = None
    bindings: list[GitHubBinding] = Field(default_factory=list)

    @field_validator("bot_login")
    @classmethod
    def _normalize_bot_login(cls, value: str | None) -> str | None:
        '''规范化机器人登录名中的空白值。'''
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _unique_binding_repos(self) -> "GitHubAgentConfig":
        '''拒绝在 ``bindings`` 中重复出现的 ``repo`` 值。

        每个仓库至多允许一个绑定。单个绑定的按事件 ``triggers`` 映射已经可表达
        “此智能体监听该仓库的 N 个事件”，因此同一仓库的多个绑定要么会重复事件
        （静默的首项优先或重复注册，参见 PR 反馈 R3），要么会无益地将事件拆分到
        多行。由于这是初始实现，且现有运维配置不依赖重复仓库绑定，故在加载配置
        时明确报错，而不是在分发时掩盖这种歧义。
        '''
        seen: set[str] = set()
        dupes: set[str] = set()
        for binding in self.bindings:
            if binding.repo in seen:
                dupes.add(binding.repo)
            seen.add(binding.repo)
        if dupes:
            raise ValueError(f"Agent github.bindings has duplicate repos {sorted(dupes)}. Each repo must appear at most once — merge their `triggers:` maps into a single binding.")
        return self


def validate_agent_name(name: str | None) -> str | None:
    '''在将自定义智能体名称用于文件系统路径前验证其有效性。'''
    if name is None:
        return None
    if not isinstance(name, str):
        raise ValueError("Invalid agent name. Expected a string or None.")
    if not AGENT_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
    return name


class AgentConfig(BaseModel):
    '''自定义智能体的配置。'''

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None
    skills: list[str] | None = None
    github: GitHubAgentConfig | None = None


MANAGED_AGENT_CONFIG_FIELDS: frozenset[str] = frozenset({"name", "description", "model", "tool_groups", "skills"})


def preserve_non_managed_fields(existing_cfg: AgentConfig) -> dict[str, object]:
    '''返回 ``existing_cfg`` 中不属于 :data:`MANAGED_AGENT_CONFIG_FIELDS` 的所有顶层字段。

    重写自定义智能体 ``config.yaml`` 的两个入口（``update_agent`` harness 工具与
    HTTP ``PATCH /api/agents/{name}`` 路由）使用此函数保留更新 API 未暴露为参数的
    手工配置字段：目前为 ``github``，以及未来加入 :class:`AgentConfig` 的任何字段。
    否则，运维人员手写的 ``github:`` 配置块会在智能体或 UI 编辑器下次修改
    ``description`` / ``model`` / ``tool_groups`` / ``skills`` 时被静默丢失。

    Pydantic v2 的 ``exclude_unset=True`` 会递归生效，因此用户未写入且使用
    Pydantic 默认值的子字段不会被具体化到字典中，文件往返后仍保持原有外观。
    '''
    return existing_cfg.model_dump(exclude_unset=True, exclude=MANAGED_AGENT_CONFIG_FIELDS)


def resolve_agent_dir(name: str, *, user_id: str | None = None) -> Path:
    '''返回智能体的磁盘目录，并优先选择按用户划分的布局。

    解析顺序：
    1. ``{base_dir}/users/{user_id}/agents/{name}/``（当前的按用户布局）。
    2. ``{base_dir}/agents/{name}/``（旧版共享布局，只读回退）。

    若两者都不存在，则返回按用户划分的路径，以便需要创建智能体的调用方写入新布局。

    参数：
        name: 已验证的智能体名称。
        user_id: 智能体所有者。默认取请求上下文中的有效用户；无认证模式下为
            ``"default"``。
    '''
    paths = get_paths()
    effective_user = user_id or get_effective_user_id()
    user_path = paths.user_agent_dir(effective_user, name)
    if user_path.exists() and (user_path / "config.yaml").exists():
        return user_path

    legacy_path = paths.agent_dir(name)
    if legacy_path.exists() and (legacy_path / "config.yaml").exists():
        return legacy_path

    return user_path


def load_agent_config(name: str | None, *, user_id: str | None = None) -> AgentConfig | None:
    '''从智能体目录加载自定义或默认智能体的配置。

    优先从按用户划分的布局读取；尚未迁移的安装会回退到旧版共享布局。

    参数：
        name: 智能体名称。
        user_id: 智能体所有者。默认取当前请求上下文中的有效用户。

    返回：
        ``AgentConfig`` 实例；若 ``name`` 为 ``None``，则返回 ``None``。

    异常：
        FileNotFoundError: 智能体目录或 config.yaml 不存在。
        ValueError: 无法解析 config.yaml。
    '''

    if name is None:
        return None

    name = validate_agent_name(name)
    agent_dir = resolve_agent_dir(name, user_id=user_id)
    config_file = agent_dir / "config.yaml"

    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    if not config_file.exists():
        raise FileNotFoundError(f"Agent config not found: {config_file}")

    try:
        with open(config_file, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse agent config {config_file}: {e}") from e

    if "name" not in data:
        data["name"] = name

    known_fields = set(AgentConfig.model_fields.keys())
    data = {k: v for k, v in data.items() if k in known_fields}

    return AgentConfig(**data)


def load_agent_soul(agent_name: str | None, *, user_id: str | None = None) -> str | None:
    '''在存在时读取自定义智能体的 SOUL.md 文件。

    SOUL.md 定义智能体的个性、价值观和行为护栏，并作为额外上下文注入主智能体的
    系统提示词。

    参数：
        agent_name: 智能体名称；默认智能体传入 None。
        user_id: 智能体所有者。默认取当前请求上下文中的有效用户。

    返回：
        SOUL.md 的字符串内容；文件不存在时返回 None。
    '''
    if agent_name:
        agent_dir = resolve_agent_dir(agent_name, user_id=user_id)
        soul_path = agent_dir / SOUL_FILENAME
        if not soul_path.exists() and not (agent_dir / "config.yaml").exists():
            paths = get_paths()
            effective_user = user_id or get_effective_user_id()
            for candidate in (
                paths.user_agent_dir(effective_user, agent_name),
                paths.agent_dir(agent_name),
            ):
                if (candidate / SOUL_FILENAME).exists():
                    soul_path = candidate / SOUL_FILENAME
                    break
    else:
        agent_dir = get_paths().base_dir
        soul_path = agent_dir / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def list_custom_agents(*, user_id: str | None = None) -> list[AgentConfig]:
    '''扫描智能体目录并返回所有有效的自定义智能体。

    返回按用户布局与旧版共享布局中的智能体并集，使迁移前的安装在迁移完成前仍然可见。
    同名的按用户条目会覆盖旧版条目。

    参数：
        user_id: 要列出其智能体的所有者。默认取当前请求上下文中的有效用户。

    返回：
        每个找到的有效智能体目录对应的 ``AgentConfig`` 列表。
    '''
    paths = get_paths()
    effective_user = user_id or get_effective_user_id()

    seen: set[str] = set()
    agents: list[AgentConfig] = []

    user_root = paths.user_agents_dir(effective_user)
    legacy_root = paths.agents_dir

    for root in (user_root, legacy_root):
        if not root.exists():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in seen:
                continue
            config_file = entry / "config.yaml"
            if not config_file.exists():
                logger.debug(f"Skipping {entry.name}: no config.yaml")
                continue

            try:
                agent_cfg = load_agent_config(entry.name, user_id=effective_user)
                if agent_cfg is None:
                    continue
                agents.append(agent_cfg)
                seen.add(entry.name)
            except Exception as e:
                logger.warning(f"Skipping agent '{entry.name}': {e}")

    agents.sort(key=lambda a: a.name)
    return agents
