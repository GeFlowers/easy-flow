'''构建主代理，并在图调用根节点统一配置追踪。

追踪回调会在 :func:`_make_lead_agent` 的图调用根节点附加到
``config["callbacks"]``。本模块及该图可达的中间件内每次调用
``create_chat_model(...)`` 时都必须传入 ``attach_tracing=False``，以免重复
生成跨度，并确保追踪处理器能够把会话和用户属性写入根追踪。
'''

from __future__ import annotations

import logging

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.runnables import RunnableConfig

from deerflow.agents.lead_agent.prompt import apply_prompt_template
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, create_summarization_middleware
from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware
from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.agents.middlewares.todo_middleware import TodoMiddleware
from deerflow.agents.middlewares.token_usage_middleware import TokenUsageMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.agents_config import load_agent_config, validate_agent_name
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.memory_config import should_use_memory_tools
from deerflow.config.subagents_config import DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN
from deerflow.models import create_chat_model
from deerflow.skills.tool_policy import ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES, filter_tools_by_skill_allowed_tools
from deerflow.skills.types import Skill
from deerflow.tracing import build_tracing_callbacks

logger = logging.getLogger(__name__)

_BOOTSTRAP_SKILL_NAMES = {"bootstrap"}
_NON_INTERACTIVE_DISABLED_TOOL_NAMES = frozenset({"ask_clarification"})

# 入站消息来自不可信外部评论者的渠道（例如任意 GitHub 仓库的评论者），其
# 运行上下文不应使用 ``update_agent`` 一类管理工具。对应的拦截逻辑位于
# :func:`_make_lead_agent`；渠道名称由
# ``ChannelManager._resolve_run_params`` 写入 ``run_context``。
_WEBHOOK_CHANNELS: frozenset[str] = frozenset({"github"})


def _default_max_total_subagents(app_config: object) -> int:
    '''从应用配置读取单次运行的子代理总数默认上限。'''
    subagents_config = getattr(app_config, "subagents", None)
    return getattr(subagents_config, "max_total_per_run", DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN)


def _append_memory_tools_without_name_conflicts(tools: list) -> None:
    '''追加记忆工具，同时保留同名的既有非记忆工具。'''
    from deerflow.agents.memory.tools import get_memory_tools

    existing_names = {getattr(tool, "name", None) for tool in tools}
    for memory_tool in get_memory_tools():
        if memory_tool.name in existing_names:
            logger.warning("Memory tool name %r already exists and was skipped.", memory_tool.name)
            continue
        tools.append(memory_tool)
        existing_names.add(memory_tool.name)


def _get_runtime_config(config: RunnableConfig) -> dict:
    '''合并旧版可配置参数与 ``LangGraph`` 运行上下文中的参数。'''
    cfg = dict(config.get("configurable", {}) or {})
    context = config.get("context", {}) or {}
    if isinstance(context, dict):
        cfg.update(context)
    return cfg


def _resolve_model_name(requested_model_name: str | None = None, *, app_config: AppConfig | None = None) -> str:
    '''安全解析运行时模型名；无效时回退默认模型，未配置模型时返回空值。'''
    app_config = app_config or get_app_config()
    default_model_name = app_config.models[0].name if app_config.models else None
    if default_model_name is None:
        raise ValueError("No chat models are configured. Please configure at least one model in config.yaml.")

    if requested_model_name and app_config.get_model_config(requested_model_name):
        return requested_model_name

    if requested_model_name and requested_model_name != default_model_name:
        logger.warning(f"Model '{requested_model_name}' not found in config; fallback to default model '{default_model_name}'.")
    return default_model_name


def _create_summarization_middleware(*, app_config: AppConfig | None = None) -> DeerFlowSummarizationMiddleware | None:
    '''根据应用配置创建会话摘要中间件。'''
    return create_summarization_middleware(app_config=app_config)


def _create_todo_list_middleware(is_plan_mode: bool) -> TodoMiddleware | None:
    '''在计划模式启用时创建待办事项中间件，否则不创建。'''
    if not is_plan_mode:
        return None

    # 与 DeerFlow 风格一致的自定义提示词。
    system_prompt = """
<todo_list_system>
You have access to the `write_todos` tool to help you manage and track complex multi-step objectives.

**CRITICAL RULES:**
- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions
- Keep EXACTLY ONE task as `in_progress` at any time (unless tasks can run in parallel)
- Update the todo list in REAL-TIME as you work - this gives users visibility into your progress
- DO NOT use this tool for simple tasks (< 3 steps) - just complete them directly

**When to Use:**
This tool is designed for complex objectives that require systematic tracking:
- Complex multi-step tasks requiring 3+ distinct steps
- Non-trivial tasks needing careful planning and execution
- User explicitly requests a todo list
- User provides multiple tasks (numbered or comma-separated list)
- The plan may need revisions based on intermediate results

**When NOT to Use:**
- Single, straightforward tasks
- Trivial tasks (< 3 steps)
- Purely conversational or informational requests
- Simple tool calls where the approach is obvious

**Best Practices:**
- Break down complex tasks into smaller, actionable steps
- Use clear, descriptive task names
- Remove tasks that become irrelevant
- Add new tasks discovered during implementation
- Don't be afraid to revise the todo list as you learn more

**Task Management:**
Writing todos takes time and tokens - use it when helpful for managing complex problems, not for simple requests.
</todo_list_system>
"""

    tool_description = """Use this tool to create and manage a structured task list for complex work sessions.

**IMPORTANT: Only use this tool for complex tasks (3+ steps). For simple requests, just do the work directly.**


Use this tool in these scenarios:
1. **Complex multi-step tasks**: When a task requires 3 or more distinct steps or actions
2. **Non-trivial tasks**: Tasks requiring careful planning or multiple operations
3. **User explicitly requests todo list**: When the user directly asks you to track tasks
4. **Multiple tasks**: When users provide a list of things to be done
5. **Dynamic planning**: When the plan may need updates based on intermediate results


Skip this tool when:
1. The task is straightforward and takes less than 3 steps
2. The task is trivial and tracking provides no benefit
3. The task is purely conversational or informational
4. It's clear what needs to be done and you can just do it


1. **Starting a task**: Mark it as `in_progress` BEFORE beginning work
2. **Completing a task**: Mark it as `completed` IMMEDIATELY after finishing
3. **Updating the list**: Add new tasks, remove irrelevant ones, or update descriptions as needed
4. **Multiple updates**: You can make several updates at once (e.g., complete one task and start the next)


- `pending`: Task not yet started
- `in_progress`: Currently working on (can have multiple if tasks run in parallel)
- `completed`: Task finished successfully


**CRITICAL: Only mark a task as completed when you have FULLY accomplished it.**

Never mark a task as completed if:
- There are unresolved issues or errors
- Work is partial or incomplete
- You encountered blockers preventing completion
- You couldn't find necessary resources or dependencies
- Quality standards haven't been met

If blocked, keep the task as `in_progress` and create a new task describing what needs to be resolved.


- Create specific, actionable items
- Break complex tasks into smaller, manageable steps
- Use clear, descriptive task names
- Update task status in real-time as you work
- Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
- Remove tasks that are no longer relevant
- **IMPORTANT**: When you write the todo list, mark your first task(s) as `in_progress` immediately
- **IMPORTANT**: Unless all tasks are completed, always have at least one task `in_progress` to show progress

Being proactive with task management demonstrates thoroughness and ensures all requirements are completed successfully.

**Remember**: If you only need a few tool calls to complete a task and it's clear what to do, it's better to just do the task directly and NOT use this tool at all.
"""

    return TodoMiddleware(system_prompt=system_prompt, tool_description=tool_description)


# ThreadDataMiddleware 必须位于 SandboxMiddleware 之前，确保可取得 thread_id。
# UploadsMiddleware 应位于 ThreadDataMiddleware 之后，以访问 thread_id。
# DanglingToolCallMiddleware 会在模型读取历史前补齐缺失的 ToolMessage。
# SummarizationMiddleware 应尽早执行，以便其他处理前先压缩上下文。
# TodoListMiddleware 应位于 ClarificationMiddleware 之前，以支持待办管理。
# TitleMiddleware 会在首次交互后生成标题。
# MemoryMiddleware 会在 TitleMiddleware 之后将对话加入记忆更新队列。
# ViewImageMiddleware 应位于 ClarificationMiddleware 之前，为语言模型注入图像详情。
# ToolErrorHandlingMiddleware 应位于 ClarificationMiddleware 之前，将工具异常转换为 ToolMessage。
# ClarificationMiddleware 应最后执行，以便在模型调用后拦截澄清请求。
def build_middlewares(
    config: RunnableConfig,
    model_name: str | None,
    agent_name: str | None = None,
    custom_middlewares: list[AgentMiddleware] | None = None,
    *,
    available_skills: set[str] | None = None,
    app_config: AppConfig | None = None,
    deferred_setup=None,
    mcp_routing_middleware: AgentMiddleware | None = None,
    user_id: str | None = None,
):
    '''按运行时配置组装主代理完整且顺序固定的中间件链。'''
    resolved_app_config = app_config or get_app_config()
    middlewares = build_lead_runtime_middlewares(app_config=resolved_app_config, lazy_init=True)

    # 始终将当前日期（以及可选的记忆）作为 <system-reminder> 注入首条
    # HumanMessage，使系统提示词保持静态并可复用前缀缓存。
    from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware

    middlewares.append(DynamicContextMiddleware(agent_name=agent_name, app_config=resolved_app_config))

    # 用户以 /skill-name 开始本轮时，确定性加载完整的 SKILL.md。这样既让基础
    # 系统提示词仅含元数据，又使用户显式激活优先于模型的相关性猜测。
    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

    middlewares.append(SkillActivationMiddleware(available_skills=available_skills, app_config=resolved_app_config, user_id=user_id))

    # 在摘要压缩前捕获已完成的任务委派和已加载的技能文件，再把持久上下文通道
    # （摘要、台账和技能）注入模型调用。
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

    middlewares.append(
        DurableContextMiddleware(
            skills_container_path=resolved_app_config.skills.container_path,
            skill_file_read_tool_names=resolved_app_config.summarization.skill_file_read_tool_names,
        )
    )

    # 配置启用时加入摘要中间件。
    summarization_middleware = _create_summarization_middleware(app_config=resolved_app_config)
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    # 计划模式启用时加入待办事项中间件。
    cfg = _get_runtime_config(config)
    is_plan_mode = cfg.get("is_plan_mode", False)
    todo_list_middleware = _create_todo_list_middleware(is_plan_mode)
    if todo_list_middleware is not None:
        middlewares.append(todo_list_middleware)

    # 令牌用量跟踪启用时加入 TokenUsageMiddleware。
    if resolved_app_config.token_usage.enabled:
        middlewares.append(TokenUsageMiddleware())

    # 加入标题生成中间件。
    middlewares.append(TitleMiddleware(app_config=resolved_app_config))

    # 加入记忆中间件（位于标题中间件之后）；工具模式启用时跳过。
    if should_use_memory_tools(resolved_app_config.memory):
        pass
    else:
        if resolved_app_config.memory.mode == "tool" and not resolved_app_config.memory.enabled:
            logger.warning("memory.mode is 'tool' but memory.enabled is false; memory tools will not be registered.")
        middlewares.append(MemoryMiddleware(agent_name=agent_name, memory_config=resolved_app_config.memory))

    # 仅当前模型支持视觉能力时加入 ViewImageMiddleware。
    # 使用 make_lead_agent 解析出的运行时 model_name，避免读取过期配置。
    model_config = resolved_app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        middlewares.append(ViewImageMiddleware())

    # 在延迟筛选器决定本次调用隐藏哪些模式前，依据路由元数据自动提升延迟的 MCP 模式。
    if mcp_routing_middleware is not None:
        middlewares.append(mcp_routing_middleware)

    # 在 tool_search 提升延迟工具前，不向模型绑定其模式。延迟集合与目录哈希
    # 来自构建阶段（工具策略筛选之后），提升状态从图状态读取。
    if deferred_setup is not None and deferred_setup.deferred_names:
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        middlewares.append(DeferredToolFilterMiddleware(deferred_setup.deferred_names, deferred_setup.catalog_hash))
        from deerflow.agents.middlewares.mcp_routing_middleware import assert_mcp_routing_before_deferred_filter

        assert_mcp_routing_before_deferred_filter(middlewares)

    # 请求到达提供方前，将所有 SystemMessage 合并成唯一的首条消息。严格后端
    # （vLLM、SGLang、Qwen、Anthropic）会拒绝非首位的 SystemMessage，详见
    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware

    middlewares.append(SystemMessageCoalescingMiddleware())

    # 加入 SubagentLimitMiddleware，以截断超额的并行任务调用。
    subagent_enabled = cfg.get("subagent_enabled", False)
    if subagent_enabled:
        max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
        max_total_subagents = cfg.get("max_total_subagents", _default_max_total_subagents(resolved_app_config))
        middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents, max_total=max_total_subagents))

    # LoopDetectionMiddleware 用于检测并打断重复的工具调用循环。
    loop_detection_config = resolved_app_config.loop_detection
    if loop_detection_config.enabled:
        middlewares.append(LoopDetectionMiddleware.from_config(loop_detection_config))

    # TokenBudgetMiddleware 用于强制执行单次运行的令牌限制。
    token_budget_config = resolved_app_config.token_budget
    if token_budget_config.enabled:
        from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware

        middlewares.append(TokenBudgetMiddleware.from_config(token_budget_config))

    # 在 ClarificationMiddleware 前注入自定义中间件。
    if custom_middlewares:
        middlewares.extend(custom_middlewares)

    # 提供方可能在工具执行后返回空 AIMessage。此时重试最终响应一次，随后持久化
    # 可见的错误回退，避免 LangChain 的无工具调用路由静默结束为成功运行。
    middlewares.append(TerminalResponseMiddleware())

    # 当提供方因安全原因终止响应时，SafetyFinishReasonMiddleware 会阻止工具执行。
    # 它注册在最终响应和自定义中间件之后，使 LangChain 逆序分派 after_model 时
    # 先执行安全处理；清空后的 tool_calls 再经过剩余记账与终止保护而不重复告警。
    safety_config = resolved_app_config.safety_finish_reason
    if safety_config.enabled:
        middlewares.append(SafetyFinishReasonMiddleware.from_config(safety_config))

    # ClarificationMiddleware 必须始终位于末尾。
    middlewares.append(ClarificationMiddleware())
    return middlewares


def _available_skill_names(agent_config, is_bootstrap: bool) -> set[str] | None:
    '''确定当前代理允许加载的技能名称集合。'''
    if is_bootstrap:
        return set(_BOOTSTRAP_SKILL_NAMES)
    if agent_config and agent_config.skills is not None:
        return set(agent_config.skills)
    return None


def _load_enabled_skills_for_tool_policy(available_skills: set[str] | None, *, app_config: AppConfig, user_id: str | None = None) -> list[Skill]:
    '''加载已启用且符合当前技能白名单的工具策略技能。'''
    try:
        from deerflow.agents.lead_agent.prompt import get_enabled_skills_for_config

        skills = get_enabled_skills_for_config(app_config, user_id=user_id)
    except Exception:
        logger.exception("Failed to load skills for allowed-tools policy")
        raise

    if available_skills is None:
        return skills
    return [skill for skill in skills if skill.name in available_skills]


def make_lead_agent(config: RunnableConfig):
    '''提供与 ``LangGraph Server`` 兼容的主代理图工厂入口。'''
    runtime_config = _get_runtime_config(config)
    runtime_app_config = runtime_config.get("app_config")
    return _make_lead_agent(config, app_config=runtime_app_config or get_app_config())


def _make_lead_agent(config: RunnableConfig, *, app_config: AppConfig):
    '''按配置、工具策略和运行上下文构造具体的主代理图。'''
    # 延迟导入，避免循环依赖。
    from deerflow.tools import get_available_tools
    from deerflow.tools.builtins import setup_agent, update_agent
    from deerflow.tools.builtins.tool_search import assemble_deferred_tools, build_mcp_routing_middleware, get_mcp_routing_hints_prompt_section

    cfg = _get_runtime_config(config)
    resolved_app_config = app_config

    # 提取用户范围技能加载所需的 user_id。LangGraph 网关会将它写入
    # config["configurable"]；缺失时回退到运行时上下文变量。
    from deerflow.runtime.user_context import get_effective_user_id

    runtime_user_id = cfg.get("user_id")
    resolved_user_id = str(runtime_user_id) if runtime_user_id else get_effective_user_id()

    thinking_enabled = cfg.get("thinking_enabled", True)
    reasoning_effort = cfg.get("reasoning_effort", None)
    requested_model_name: str | None = cfg.get("model_name") or cfg.get("model")
    is_plan_mode = cfg.get("is_plan_mode", False)
    subagent_enabled = cfg.get("subagent_enabled", False)
    max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
    max_total_subagents = cfg.get("max_total_subagents", _default_max_total_subagents(resolved_app_config))
    is_bootstrap = cfg.get("is_bootstrap", False)
    non_interactive = bool(cfg.get("non_interactive", False))
    agent_name = validate_agent_name(cfg.get("agent_name"))

    agent_config = load_agent_config(agent_name) if not is_bootstrap else None
    available_skills = _available_skill_names(agent_config, is_bootstrap)
    # 自定义代理可从自身配置取得模型；缺失时由 _resolve_model_name 选择默认值。
    agent_model_name = agent_config.model if agent_config and agent_config.model else None

    # 最终模型名依次取请求、代理配置、全局默认值；未知名称会回退。
    model_name = _resolve_model_name(requested_model_name or agent_model_name, app_config=resolved_app_config)

    model_config = resolved_app_config.get_model_config(model_name)

    if model_config is None:
        raise ValueError("No chat model could be resolved. Please configure at least one model in config.yaml or provide a valid 'model_name'/'model' in the request.")
    if thinking_enabled and not model_config.supports_thinking:
        logger.warning(f"Thinking mode is enabled but model '{model_name}' does not support it; fallback to non-thinking mode.")
        thinking_enabled = False

    logger.info(
        "Create Agent(%s) -> thinking_enabled: %s, reasoning_effort: %s, model_name: %s, is_plan_mode: %s, subagent_enabled: %s, max_concurrent_subagents: %s, max_total_subagents: %s",
        agent_name or "default",
        thinking_enabled,
        reasoning_effort,
        model_name,
        is_plan_mode,
        subagent_enabled,
        max_concurrent_subagents,
        max_total_subagents,
    )

    # 注入供 LangSmith 追踪标记使用的运行元数据。
    if "metadata" not in config:
        config["metadata"] = {}

    config["metadata"].update(
        {
            "agent_name": agent_name or "default",
            "model_name": model_name or "default",
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort,
            "is_plan_mode": is_plan_mode,
            "subagent_enabled": subagent_enabled,
            "tool_groups": agent_config.tool_groups if agent_config else None,
            "available_skills": sorted(available_skills) if available_skills is not None else None,
        }
    )

    # 在图调用根节点注入追踪回调，使一次 LangGraph 运行形成一条追踪，并将节点、
    # 语言模型和工具调用作为子跨度；同时让 Langfuse 处理器收到
    # ``on_chain_start(parent_run_id=None)``，从 ``config["metadata"]`` 向追踪
    # 传播 ``langfuse_session_id`` 与 ``langfuse_user_id``。若不在根节点附加，
    # 模型会成为嵌套观测，处理器将移除 ``langfuse_*`` 键。
    tracing_callbacks = build_tracing_callbacks()
    if tracing_callbacks:
        existing = config.get("callbacks") or []
        if not isinstance(existing, list):
            existing = list(existing)
        config["callbacks"] = [*existing, *tracing_callbacks]

    skills_for_tool_policy = _load_enabled_skills_for_tool_policy(available_skills, app_config=resolved_app_config, user_id=resolved_user_id)

    # 构建技能搜索配置（延迟发现），由 skills.deferred_discovery 控制，且与
    # tool_search.enabled 相互独立。
    from deerflow.skills.describe import build_skill_search_setup

    skill_search_enabled = resolved_app_config.skills.deferred_discovery
    container_base_path = resolved_app_config.skills.container_path

    if is_bootstrap:
        # 初始自定义代理创建流程使用最小提示词的专用引导代理。
        # 有意收窄引导技能集合，确保自定义代理自身配置出现前创建行为保持确定。
        bootstrap_skills = [s for s in skills_for_tool_policy if s.name in _BOOTSTRAP_SKILL_NAMES]
        skill_setup = build_skill_search_setup(
            bootstrap_skills,
            enabled=skill_search_enabled,
            container_base_path=container_base_path,
        )
        raw_tools = get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled, app_config=resolved_app_config) + [setup_agent]
        filtered = filter_tools_by_skill_allowed_tools(raw_tools, skills_for_tool_policy, always_allowed_tool_names=ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
        if non_interactive:
            filtered = [tool for tool in filtered if tool.name not in _NON_INTERACTIVE_DISABLED_TOOL_NAMES]
        final_tools, setup = assemble_deferred_tools(filtered, enabled=resolved_app_config.tool_search.enabled)
        mcp_routing_middleware = build_mcp_routing_middleware(
            final_tools,
            setup,
            top_k=resolved_app_config.tool_search.auto_promote_top_k,
        )
        if skill_setup.describe_skill_tool:
            final_tools.append(skill_setup.describe_skill_tool)
        if should_use_memory_tools(resolved_app_config.memory):
            _append_memory_tools_without_name_conflicts(final_tools)
        return create_agent(
            model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, app_config=resolved_app_config, attach_tracing=False),
            tools=final_tools,
            middleware=build_middlewares(
                config,
                model_name=model_name,
                available_skills=set(_BOOTSTRAP_SKILL_NAMES),
                app_config=resolved_app_config,
                deferred_setup=setup,
                mcp_routing_middleware=mcp_routing_middleware,
                user_id=resolved_user_id,
            ),
            system_prompt=apply_prompt_template(
                subagent_enabled=subagent_enabled,
                max_concurrent_subagents=max_concurrent_subagents,
                max_total_subagents=max_total_subagents,
                available_skills=set(_BOOTSTRAP_SKILL_NAMES),
                app_config=resolved_app_config,
                deferred_names=setup.deferred_names,
                user_id=resolved_user_id,
                skill_names=skill_setup.skill_names or None,
            ),
            state_schema=ThreadState,
        )

    # 自定义代理可通过 update_agent 修改自身 SOUL.md 和配置；默认代理（无
    # agent_name）不暴露此工具。使用工具策略筛选后的同一技能列表构建技能搜索配置，
    # 使 describe_skill 仅暴露允许的技能。
    skill_setup = build_skill_search_setup(
        skills_for_tool_policy,
        enabled=skill_search_enabled,
        container_base_path=container_base_path,
    )
    # 对 webhook 渠道（目前仅 ``github``）触发的运行隐藏 ``update_agent``。这类
    # 提示词来自任意外部评论者；只要能在已配置仓库发表评论并输入 ``@<bot>``，便能
    # 触发运行。暴露该工具会让评论者持久修改代理的 ``tool_groups``、``SOUL.md`` 或
    # ``model``。自我修改只应存在于聊天界面和 HTTP 接口等受运营者信任的入口，不应
    # 存在于 webhook 分发流程。渠道名称由 ``ChannelManager._resolve_run_params``
    # 写入 ``run_context``；引导和直接调用未设置该值，因此仍可使用 ``update_agent``。
    channel_name = cfg.get("channel_name")
    is_webhook_channel = channel_name in _WEBHOOK_CHANNELS
    extra_tools = [update_agent] if agent_name and not is_webhook_channel else []
    # 默认主代理，保持既有行为。
    raw_tools = get_available_tools(model_name=model_name, groups=agent_config.tool_groups if agent_config else None, subagent_enabled=subagent_enabled, app_config=resolved_app_config)
    filtered = filter_tools_by_skill_allowed_tools(raw_tools + extra_tools, skills_for_tool_policy, always_allowed_tool_names=ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
    if non_interactive:
        filtered = [tool for tool in filtered if tool.name not in _NON_INTERACTIVE_DISABLED_TOOL_NAMES]
    final_tools, setup = assemble_deferred_tools(filtered, enabled=resolved_app_config.tool_search.enabled)
    mcp_routing_middleware = build_mcp_routing_middleware(
        final_tools,
        setup,
        top_k=resolved_app_config.tool_search.auto_promote_top_k,
    )
    mcp_routing_hints_section = get_mcp_routing_hints_prompt_section(filtered, deferred_names=setup.deferred_names)
    if skill_setup.describe_skill_tool:
        final_tools.append(skill_setup.describe_skill_tool)
    if should_use_memory_tools(resolved_app_config.memory):
        _append_memory_tools_without_name_conflicts(final_tools)
    return create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, reasoning_effort=reasoning_effort, app_config=resolved_app_config, attach_tracing=False),
        tools=final_tools,
        middleware=build_middlewares(
            config,
            model_name=model_name,
            agent_name=agent_name,
            available_skills=available_skills,
            app_config=resolved_app_config,
            deferred_setup=setup,
            mcp_routing_middleware=mcp_routing_middleware,
            user_id=resolved_user_id,
        ),
        system_prompt=apply_prompt_template(
            subagent_enabled=subagent_enabled,
            max_concurrent_subagents=max_concurrent_subagents,
            max_total_subagents=max_total_subagents,
            agent_name=agent_name,
            available_skills=available_skills,
            app_config=resolved_app_config,
            deferred_names=setup.deferred_names,
            mcp_routing_hints_section=mcp_routing_hints_section,
            user_id=resolved_user_id,
            skill_names=skill_setup.skill_names or None,
        ),
        state_schema=ThreadState,
    )
