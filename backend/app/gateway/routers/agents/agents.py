'''提供自定义 Agent 的列表、读取、创建、修改和删除 API。'''

import asyncio
import logging
import re
import shutil

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.agents_api_config import get_agents_api_config
from deerflow.config.agents_config import AgentConfig, list_custom_agents, load_agent_config, load_agent_soul, preserve_non_managed_fields
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["agents"])

AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class AgentResponse(BaseModel):
    '''返回自定义智能体的基础配置及可选角色说明。'''

    name: str = Field(..., description="Agent name (hyphen-case)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Optional skill whitelist (None=all, []=none)")
    soul: str | None = Field(default=None, description="SOUL.md content")


class AgentsListResponse(BaseModel):
    '''封装当前用户可见的自定义智能体列表。'''

    agents: list[AgentResponse]


class AgentCreateRequest(BaseModel):
    '''接收新建自定义智能体所需的名称、权限范围和角色说明。'''

    name: str = Field(..., description="Agent name (must match ^[A-Za-z0-9-]+$, stored as lowercase)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Optional skill whitelist (None=all enabled, []=none)")
    soul: str = Field(default="", description="SOUL.md content — agent personality and behavioral guardrails")


class AgentUpdateRequest(BaseModel):
    '''接收自定义智能体可修改字段；未提供的字段保持原配置。'''

    description: str | None = Field(default=None, description="Updated description")
    model: str | None = Field(default=None, description="Updated model override")
    tool_groups: list[str] | None = Field(default=None, description="Updated tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Updated skill whitelist (None=all, []=none)")
    soul: str | None = Field(default=None, description="Updated SOUL.md content")


def _validate_agent_name(name: str) -> None:
    '''校验 Agent 名称仅含字母、数字和连字符；不符合时返回 422。'''
    if not AGENT_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid agent name '{name}'. Must match ^[A-Za-z0-9-]+$ (letters, digits, and hyphens only).",
        )


def _normalize_agent_name(name: str) -> str:
    '''将 Agent 名称转为小写，统一文件系统中的名称匹配。'''
    return name.lower()


def _require_agents_api_enabled() -> None:
    '''自定义 Agent 管理 API 未启用时拒绝请求。'''
    if not get_agents_api_config().enabled:
        raise HTTPException(
            status_code=403,
            detail=("Custom-agent management API is disabled. Set agents_api.enabled=true to expose agent and user-profile routes over HTTP."),
        )


def _agent_config_to_response(agent_cfg: AgentConfig, include_soul: bool = False, *, user_id: str | None = None) -> AgentResponse:
    '''将 Agent 配置转换为 API 响应，并按需读取 SOUL.md 正文。'''
    soul: str | None = None
    if include_soul:
        soul = load_agent_soul(agent_cfg.name, user_id=user_id) or ""

    return AgentResponse(
        name=agent_cfg.name,
        description=agent_cfg.description,
        model=agent_cfg.model,
        tool_groups=agent_cfg.tool_groups,
        skills=agent_cfg.skills,
        soul=soul,
    )


@router.get(
    "/agents",
    response_model=AgentsListResponse,
    summary="List Custom Agents",
    description="List all custom agents available in the agents directory, including their soul content.",
)
async def list_agents() -> AgentsListResponse:
    '''列出当前用户可访问的自定义 agent。

        返回：
            当前用户可访问的自定义智能体列表，包含元数据和角色说明内容。
    '''
    _require_agents_api_enabled()

    user_id = get_effective_user_id()
    try:
        agents = list_custom_agents(user_id=user_id)
        return AgentsListResponse(agents=[_agent_config_to_response(a, include_soul=True, user_id=user_id) for a in agents])
    except Exception as e:
        logger.error(f"Failed to list agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list agents: {str(e)}")


@router.get(
    "/agents/check",
    summary="Check Agent Name",
    description="Validate an agent name and check if it is available (case-insensitive).",
)
async def check_agent_name(name: str) -> dict:
    '''校验规范化名称是否同时避开用户目录和遗留共享目录中的已有 Agent。'''
    _require_agents_api_enabled()
    _validate_agent_name(name)
    normalized = _normalize_agent_name(name)
    user_id = get_effective_user_id()
    paths = get_paths()
    # 用户级目录和遗留共享目录都参与冲突检查，避免名称遮蔽尚未迁移的旧 Agent。
    available = not paths.user_agent_dir(user_id, normalized).exists() and not paths.agent_dir(normalized).exists()
    return {"available": available, "name": normalized}


@router.get(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="Get Custom Agent",
    description="Retrieve details and SOUL.md content for a specific custom agent.",
)
async def get_agent(name: str) -> AgentResponse:
    '''按名称读取当前用户可访问的自定义 agent。

        Args:
            name: The agent name.

        Returns:
            Agent details including SOUL.md content.

        Raises:
            HTTPException: 404 if agent not found.
    '''
    _require_agents_api_enabled()
    _validate_agent_name(name)
    name = _normalize_agent_name(name)
    user_id = get_effective_user_id()

    try:
        agent_cfg = load_agent_config(name, user_id=user_id)
        return _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        logger.error(f"Failed to get agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get agent: {str(e)}")


@router.post(
    "/agents",
    response_model=AgentResponse,
    status_code=201,
    summary="Create Custom Agent",
    description="Create a new custom agent with its config and SOUL.md.",
)
async def create_agent_endpoint(request: AgentCreateRequest) -> AgentResponse:
    '''校验配置并创建新的自定义 agent。

        Args:
            request: The agent creation request.

        Returns:
            The created agent details.

        Raises:
            HTTPException: 409 if agent already exists, 422 if name is invalid.
    '''
    _require_agents_api_enabled()
    _validate_agent_name(request.name)
    normalized_name = _normalize_agent_name(request.name)
    user_id = get_effective_user_id()
    paths = get_paths()

    def _create_agent() -> AgentResponse | None:
        '''在工作线程中创建代理目录和配置文件，并返回其响应模型。'''
        # 基础目录解析、存在性检查、目录和文件创建、回读及失败清理都会阻塞文件系统操作，
        # 因此放在线程池中执行，避免阻塞事件循环。
        agent_dir = paths.user_agent_dir(user_id, normalized_name)
        legacy_dir = paths.agent_dir(normalized_name)

        if legacy_dir.exists():
            return None  # 通知调用方返回 409。

        try:
            try:
                agent_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                return None  # 通知调用方返回 409。
            # 写入 config.yaml。
            config_data: dict = {"name": normalized_name}
            if request.description:
                config_data["description"] = request.description
            if request.model is not None:
                config_data["model"] = request.model
            if request.tool_groups is not None:
                config_data["tool_groups"] = request.tool_groups
            if request.skills is not None:
                config_data["skills"] = request.skills

            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

            # 写入 SOUL.md。
            soul_file = agent_dir / "SOUL.md"
            soul_file.write_text(request.soul, encoding="utf-8")

            logger.info(f"Created agent '{normalized_name}' at {agent_dir}")

            agent_cfg = load_agent_config(normalized_name, user_id=user_id)
            return _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id)
        except Exception:
            # 向上抛出异常前清理未完整创建的目录。
            if agent_dir.exists():
                shutil.rmtree(agent_dir)
            raise

    try:
        response = await asyncio.to_thread(_create_agent)
    except Exception as e:
        logger.error(f"Failed to create agent '{request.name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")

    if response is None:
        raise HTTPException(status_code=409, detail=f"Agent '{normalized_name}' already exists")

    return response


@router.put(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="Update Custom Agent",
    description="Update an existing custom agent's config and/or SOUL.md.",
)
async def update_agent(name: str, request: AgentUpdateRequest) -> AgentResponse:
    '''更新已有自定义 agent 的配置或资料。

        参数：
            name：智能体名称。
            request：更新请求，所有字段均可选。

        Returns:
            更新后的智能体资料。

        Raises:
            HTTPException：未找到智能体时返回 404。
    '''
    _require_agents_api_enabled()
    _validate_agent_name(name)
    name = _normalize_agent_name(name)
    user_id = get_effective_user_id()

    try:
        agent_cfg = load_agent_config(name, user_id=user_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    paths = get_paths()
    agent_dir = paths.user_agent_dir(user_id, name)
    legacy_dir = paths.agent_dir(name)
    # 必须检查 config.yaml，而不能只判断目录存在：用户目录可能只有 memory.json（用户首次与旧版
    # 共享智能体对话时写入，早于此路由调用）。仅用 .exists() 会漏掉该情况，进而在只含记忆文件的
    # 目录中静默创建全新的 config.yaml 和 SOUL.md，而不是阻止更新。此检查与
    # resolve_agent_dir 的保护逻辑一致，见 #3390。
    if not (agent_dir / "config.yaml").exists() and (legacy_dir / "config.yaml").exists():
        raise HTTPException(
            status_code=409,
            detail=(f"Agent '{name}' only exists in the legacy shared layout and is not scoped to a user; legacy agents are read-only and cannot be updated through this API."),
        )

    try:
        # 请求包含配置字段时才更新配置。通过 model_fields_set 区分“未提供字段”和“显式设为 null”；
        # 对技能字段而言，None 表示“继承全部”，而不是“保持原值”，因此必须区分。
        fields_set = request.model_fields_set
        config_changed = bool(fields_set & {"description", "model", "tool_groups", "skills"})

        if config_changed:
            updated: dict = {
                "name": agent_cfg.name,
                "description": request.description if "description" in fields_set else agent_cfg.description,
            }
            new_model = request.model if "model" in fields_set else agent_cfg.model
            if new_model is not None:
                updated["model"] = new_model

            new_tool_groups = request.tool_groups if "tool_groups" in fields_set else agent_cfg.tool_groups
            if new_tool_groups is not None:
                updated["tool_groups"] = new_tool_groups

            # skills：None 表示继承全部，[] 表示不启用技能，列表表示仅允许其中的技能。
            if "skills" in fields_set:
                new_skills = request.skills
            else:
                new_skills = agent_cfg.skills
            if new_skills is not None:
                updated["skills"] = new_skills

            # 保留此路由不管理的所有 AgentConfig 顶层字段（目前包括 ``github:``，也包括将来新增的
            # 字段）。框架的 ``update_agent`` 工具也使用同一辅助函数，避免管理员从网页修改智能体
            # 描述时意外删除手工配置的 ``github:`` 绑定，导致后续 Webhook 无法在注册表中找到智能体。
            for key, value in preserve_non_managed_fields(agent_cfg).items():
                updated.setdefault(key, value)

            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(updated, f, default_flow_style=False, allow_unicode=True)

        # 请求包含角色说明时同步更新智能体的 SOUL.md 文件。
        if request.soul is not None:
            soul_path = agent_dir / "SOUL.md"
            soul_path.write_text(request.soul, encoding="utf-8")

        logger.info(f"Updated agent '{name}'")

        refreshed_cfg = load_agent_config(name, user_id=user_id)
        return _agent_config_to_response(refreshed_cfg, include_soul=True, user_id=user_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")


class UserProfileResponse(BaseModel):
    '''返回当前用户的全局资料内容；文件尚不存在时内容为空。'''

    content: str | None = Field(default=None, description="USER.md 内容；文件尚未创建时为 null")


class UserProfileUpdateRequest(BaseModel):
    '''接收用于创建或替换全局 USER.md 资料的正文。'''

    content: str = Field(default="", description="USER.md 内容，用于描述用户背景和偏好")


@router.get(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="Get User Profile",
    description="Read the global USER.md file that is injected into all custom agents.",
)
async def get_user_profile() -> UserProfileResponse:
    '''读取当前用户的 USER.md 全局资料内容。

        返回：
            用户资料响应；USER.md 尚不存在时，content 为 None。
    '''
    _require_agents_api_enabled()

    try:
        user_md_path = get_paths().user_md_file
        if not user_md_path.exists():
            return UserProfileResponse(content=None)
        raw = user_md_path.read_text(encoding="utf-8").strip()
        return UserProfileResponse(content=raw or None)
    except Exception as e:
        logger.error(f"Failed to read user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read user profile: {str(e)}")


@router.put(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="Update User Profile",
    description="Write the global USER.md file that is injected into all custom agents.",
)
async def update_user_profile(request: UserProfileUpdateRequest) -> UserProfileResponse:
    '''创建或覆盖当前用户的 USER.md 全局资料。

        参数：
            request：包含新 USER.md 内容的更新请求。

        返回：
            包含已保存内容的用户资料响应。
    '''
    _require_agents_api_enabled()

    try:
        paths = get_paths()
        paths.base_dir.mkdir(parents=True, exist_ok=True)
        paths.user_md_file.write_text(request.content, encoding="utf-8")
        logger.info(f"Updated USER.md at {paths.user_md_file}")
        return UserProfileResponse(content=request.content or None)
    except Exception as e:
        logger.error(f"Failed to update user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update user profile: {str(e)}")


@router.delete(
    "/agents/{name}",
    status_code=204,
    summary="Delete Custom Agent",
    description="Delete a custom agent and all its files (config, SOUL.md, memory).",
)
async def delete_agent(name: str) -> None:
    '''删除指定的自定义 agent 及其关联配置。

        Args:
            name: The agent name.

        异常：
            HTTPException：不存在用户专属副本时返回 404；仅存在旧版共享副本时返回 409，提示执行迁移脚本。
    '''
    _require_agents_api_enabled()
    _validate_agent_name(name)
    name = _normalize_agent_name(name)
    user_id = get_effective_user_id()
    paths = get_paths()

    def _remove_agent_dir() -> tuple[str, str]:
        '''在工作线程中删除代理目录，并返回代理名称和实际路径。'''
        # 解析基础目录、检查目录是否存在（`exists`）和删除目录（`rmtree`）都会阻塞文件系统操作，
        # 因此放在线程池中执行，避免阻塞事件循环。
        agent_dir = paths.user_agent_dir(user_id, name)
        if not agent_dir.exists():
            outcome = "legacy" if paths.agent_dir(name).exists() else "missing"
            return outcome, str(agent_dir)
        shutil.rmtree(agent_dir)
        return "deleted", str(agent_dir)

    try:
        outcome, agent_dir = await asyncio.to_thread(_remove_agent_dir)
    except Exception as e:
        logger.error(f"Failed to delete agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")

    if outcome == "legacy":
        raise HTTPException(
            status_code=409,
            detail=(f"Agent '{name}' only exists in the legacy shared layout and is not scoped to a user; legacy agents are read-only and cannot be deleted through this API."),
        )
    if outcome == "missing":
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    logger.info(f"Deleted agent '{name}' from {agent_dir}")
