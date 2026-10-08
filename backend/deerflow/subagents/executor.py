'''负责构造并运行子代理，隔离事件循环、传播运行上下文并汇总任务状态。'''

import asyncio
import atexit
import html
import logging
import os
import threading
import uuid
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextvars import Context, copy_context
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain.tools import BaseTool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from deerflow.agents.thread_state import SandboxState, ThreadDataState, ThreadState
from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.skills.tool_policy import filter_tools_by_skill_allowed_tools
from deerflow.skills.types import Skill
from deerflow.subagents.config import SubagentConfig, resolve_subagent_model_name
from deerflow.subagents.step_events import capture_new_step_messages
from deerflow.subagents.token_collector import SubagentTokenCollector
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY
from deerflow.tracing import build_tracing_callbacks, inject_langfuse_metadata
from deerflow.utils.messages import message_content_to_text

if TYPE_CHECKING:
    # 仅用于类型标注；运行时在 _build_initial_state 内延迟导入，避免工具包初始化时
    # 通过 task_tool 反向导入尚未完成初始化的 subagents 包。
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

logger = logging.getLogger(__name__)


_previous_shutdown_isolated_subagent_loop = globals().get("_shutdown_isolated_subagent_loop")
if callable(_previous_shutdown_isolated_subagent_loop):
    atexit.unregister(_previous_shutdown_isolated_subagent_loop)
    _previous_shutdown_isolated_subagent_loop()


class SubagentStatus(Enum):
    '''枚举子代理从排队到运行结束的生命周期状态。'''

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        '''判断状态是否已进入完成、失败、取消或超时等不可逆终态。'''
        return self in {
            type(self).COMPLETED,
            type(self).FAILED,
            type(self).CANCELLED,
            type(self).TIMED_OUT,
        }


@dataclass
class SubagentResult:
    '''保存子代理执行结果、错误、消息、令牌统计和协作取消信号。'''

    task_id: str
    trace_id: str
    status: SubagentStatus
    result: str | None = None
    error: str | None = None
    stop_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    ai_messages: list[dict[str, Any]] | None = None
    token_usage_records: list[dict[str, int | str | None]] = field(default_factory=list)
    usage_reported: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _state_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self):
        '''为未显式提供消息列表的结果创建可追加的空列表。'''
        if self.ai_messages is None:
            self.ai_messages = []

    def update_token_usage_records(self, records: list[dict[str, int | str | None]]) -> None:
        '''在任务尚未终止时原子替换令牌用量快照。'''
        with self._state_lock:
            if not self.status.is_terminal:
                self.token_usage_records = list(records)

    def try_set_terminal(
        self,
        status: SubagentStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        stop_reason: str | None = None,
        completed_at: datetime | None = None,
        ai_messages: list[dict[str, Any]] | None = None,
        token_usage_records: list[dict[str, int | str | None]] | None = None,
    ) -> bool:
        '''校验终态后只允许首次写入结果，避免超时与执行完成竞争时互相覆盖。'''
        if not status.is_terminal:
            raise ValueError(f"Status {status} is not terminal")

        with self._state_lock:
            if self.status.is_terminal:
                return False

            if result is not None:
                self.result = result
            if error is not None:
                self.error = error
            if stop_reason is not None:
                self.stop_reason = stop_reason
            if ai_messages is not None:
                self.ai_messages = ai_messages
            if token_usage_records is not None:
                self.token_usage_records = token_usage_records
            self.completed_at = completed_at or datetime.now()
            self.status = status
            return True


def _extract_final_result(final_state: Any, *, trace_id: str, name: str) -> str:
    '''从最终状态中提取最后一条助手消息；缺少状态或消息时返回稳定的空响应文本。'''
    if final_state is None:
        logger.warning(f"[trace={trace_id}] Subagent {name} no final state")
        return "No response generated"

    messages = final_state.get("messages", [])
    logger.info(f"[trace={trace_id}] Subagent {name} final messages count: {len(messages)}")

    last_ai_message = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_ai_message = msg
            break

    if last_ai_message is not None:
        text = message_content_to_text(last_ai_message.content)
        return text if text else "No response generated"

    if messages:
        last_message = messages[-1]
        logger.warning(f"[trace={trace_id}] Subagent {name} no AIMessage found, using last message: {type(last_message)}")
        raw_content = last_message.content if hasattr(last_message, "content") else str(last_message)
        text = message_content_to_text(raw_content)
        return text if text else "No response generated"

    logger.warning(f"[trace={trace_id}] Subagent {name} no messages in final state")
    return "No response generated"


def _extract_llm_error_fallback(final_state: Any) -> str | None:
    '''识别错误处理中间件生成的终止助手消息，与真实的部分执行结果区分。'''
    if final_state is None:
        return None

    for message in reversed(final_state.get("messages", [])):
        if not isinstance(message, AIMessage):
            continue

        metadata = message.additional_kwargs
        if metadata.get("deerflow_error_fallback") is not True:
            return None

        content = message_content_to_text(message.content).strip()
        if content:
            return content

        # 正常的错误回退消息始终含有面向用户的文本；以下分支仅防御未来中间件意外产生空消息。
        detail = metadata.get("error_detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return "LLM request failed"

    return None


# 保存后台子代理的结果，供状态查询、取消和清理接口共用。
_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

# 线程池仅负责调度后台任务；真正的异步代理运行复用下方隔离事件循环。
_scheduler_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-scheduler-")

# 当父任务已有事件循环时，将子代理送入独立的常驻循环执行，避免每次新建循环导致
# 绑定于循环的异步客户端资源无法复用或被过早关闭。
_isolated_subagent_loop: asyncio.AbstractEventLoop | None = None
_isolated_subagent_loop_thread: threading.Thread | None = None
_isolated_subagent_loop_started: threading.Event | None = None
_isolated_subagent_loop_lock = threading.Lock()


def _run_isolated_subagent_loop(
    loop: asyncio.AbstractEventLoop,
    started_event: threading.Event,
) -> None:
    '''在线程中运行专用异步循环，并在启动后通知等待方。'''
    asyncio.set_event_loop(loop)
    loop.call_soon(started_event.set)
    try:
        loop.run_forever()
    finally:
        started_event.clear()


def _shutdown_isolated_subagent_loop() -> None:
    '''停止隔离循环并等待线程退出；仅在循环确实停止后关闭它。'''
    global _isolated_subagent_loop, _isolated_subagent_loop_thread, _isolated_subagent_loop_started

    with _isolated_subagent_loop_lock:
        loop = _isolated_subagent_loop
        thread = _isolated_subagent_loop_thread
        _isolated_subagent_loop = None
        _isolated_subagent_loop_thread = None
        _isolated_subagent_loop_started = None

    if loop is None:
        return

    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)

    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=1)

    thread_stopped = thread is None or not thread.is_alive()
    loop_stopped = not loop.is_running()

    if not loop.is_closed():
        if thread_stopped and loop_stopped:
            loop.close()
        else:
            logger.warning(
                "Skipping close of isolated subagent loop because shutdown did not complete within timeout (thread_alive=%s, loop_running=%s)",
                thread is not None and thread.is_alive(),
                loop.is_running(),
            )


atexit.register(_shutdown_isolated_subagent_loop)


def _get_isolated_subagent_loop() -> asyncio.AbstractEventLoop:
    '''返回正在运行的隔离循环；若实例失效则创建线程并等待其就绪。'''
    global _isolated_subagent_loop, _isolated_subagent_loop_thread, _isolated_subagent_loop_started
    with _isolated_subagent_loop_lock:
        thread_is_alive = _isolated_subagent_loop_thread is not None and _isolated_subagent_loop_thread.is_alive()
        loop_is_usable = _isolated_subagent_loop is not None and not _isolated_subagent_loop.is_closed() and _isolated_subagent_loop.is_running() and thread_is_alive

        if not loop_is_usable:
            loop = asyncio.new_event_loop()
            started_event = threading.Event()
            thread = threading.Thread(
                target=_run_isolated_subagent_loop,
                args=(loop, started_event),
                name="subagent-persistent-loop",
                daemon=True,
            )
            thread.start()
            if not started_event.wait(timeout=5):
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=1)
                loop.close()
                raise RuntimeError("Timed out starting isolated subagent event loop")
            _isolated_subagent_loop = loop
            _isolated_subagent_loop_thread = thread
            _isolated_subagent_loop_started = started_event

        if _isolated_subagent_loop is None:
            raise RuntimeError("Isolated subagent event loop is not initialized")
        return _isolated_subagent_loop


def _submit_to_isolated_loop_in_context(
    context: Context,
    coro_factory: Callable[[], Coroutine[Any, Any, SubagentResult]],
) -> Future[SubagentResult]:
    '''在父任务复制的上下文中向隔离循环提交协程，保留用户和追踪上下文。'''
    return context.run(
        lambda: asyncio.run_coroutine_threadsafe(
            coro_factory(),
            _get_isolated_subagent_loop(),
        )
    )


def _filter_tools(
    all_tools: list[BaseTool],
    allowed: list[str] | None,
    disallowed: list[str] | None,
) -> list[BaseTool]:
    '''先应用允许列表再应用拒绝列表，得到该子代理实际可调用的工具集合。'''
    filtered = all_tools

    # 配置了允许列表时，只保留名单中的工具。
    if allowed is not None:
        allowed_set = set(allowed)
        filtered = [t for t in filtered if t.name in allowed_set]

    # 拒绝列表在允许列表之后生效，显式拒绝优先。
    if disallowed is not None:
        disallowed_set = set(disallowed)
        filtered = [t for t in filtered if t.name not in disallowed_set]

    return filtered


class SubagentExecutor:
    '''创建并执行一个子代理，同时管理工具策略、上下文继承和结果生命周期。'''

    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        app_config: AppConfig | None = None,
        parent_model: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
        user_id: str | None = None,
        user_role: str | None = None,
        oauth_provider: str | None = None,
        oauth_id: str | None = None,
        run_id: str | None = None,
        channel_user_id: str | None = None,
        deerflow_trace_id: str | None = None,
    ):
        '''保存代理执行所需的身份、配置、工具、沙箱和追踪上下文。'''
        self.config = config
        self.app_config = app_config
        self.parent_model = parent_model
        # 已有明确模型或应用配置时立即解析；否则延迟到创建代理时读取配置，
        # 允许无配置文件的测试和嵌入式调用先构造执行器。
        if config.model != "inherit" or parent_model is not None or app_config is not None:
            self.model_name: str | None = resolve_subagent_model_name(config, parent_model, app_config=app_config)
        else:
            self.model_name = None
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.thread_id = thread_id
        # 顶层调用未提供追踪标识时生成短 ID，便于日志关联。
        self.trace_id = trace_id or str(uuid.uuid4())[:8]
        self.user_id = user_id
        # 将父运行的权限身份传给子代理及其工具调用。
        self.user_role = user_role
        self.oauth_provider = oauth_provider
        self.oauth_id = oauth_id
        self.run_id = run_id
        # 群聊线程由多人共享；子代理命令必须使用触发本次委派的发送者身份，
        # 不能因线程共享而丢失用户归属。
        self.channel_user_id = channel_user_id
        self.deerflow_trace_id = deerflow_trace_id

        self._base_tools = _filter_tools(
            tools,
            config.tools,
            config.disallowed_tools,
        )
        self.tools = self._base_tools
        # 收集可报告停止原因的预算与循环检测中间件；运行结束后逐个检查，
        # 让主代理知道是哪项限制提前结束了子代理。
        self._stop_reason_middlewares: list[Any] = []

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")

    def _create_agent(self, tools: list[BaseTool] | None = None, *, deferred_setup: "DeferredToolSetup | None" = None):
        '''依据当前模型和运行配置构建代理图及共享运行中间件。'''
        app_config = self.app_config or get_app_config()
        if self.model_name is None:
            self.model_name = resolve_subagent_model_name(self.config, self.parent_model, app_config=app_config)
        model = create_chat_model(name=self.model_name, thinking_enabled=False, app_config=app_config, attach_tracing=False)

        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        # 与主代理共用中间件装配逻辑，并用代理名读取专属令牌预算。
        mcp_routing_middleware = None
        if deferred_setup is not None and deferred_setup.deferred_names:
            from deerflow.tools.builtins.tool_search import build_mcp_routing_middleware

            mcp_routing_middleware = build_mcp_routing_middleware(
                tools if tools is not None else self.tools,
                deferred_setup,
                top_k=app_config.tool_search.auto_promote_top_k,
            )
        middleware_kwargs = {
            "app_config": app_config,
            "model_name": self.model_name,
            "lazy_init": True,
            "deferred_setup": deferred_setup,
            "agent_name": self.config.name,
        }
        if mcp_routing_middleware is not None:
            middleware_kwargs["mcp_routing_middleware"] = mcp_routing_middleware
        middlewares = build_subagent_runtime_middlewares(**middleware_kwargs)
        # 通过能力探测收集报告停止原因的中间件，避免此模块依赖具体实现类，
        # 并保留多个保护措施同时工作的可能性。
        self._stop_reason_middlewares = [m for m in middlewares if hasattr(m, "consume_stop_reason")]

        # 系统提示已在初始状态中与技能说明合并；避免某些模型不接受多个系统消息。
        return create_agent(
            model=model,
            tools=tools if tools is not None else self.tools,
            middleware=middlewares,
            system_prompt=None,
            state_schema=ThreadState,
            checkpointer=False,
        )

    def _consume_guard_stop_reason(self) -> str | None:
        '''读取首个中间件报告的停止原因，并消费该次运行的临时标记。'''
        for mw in self._stop_reason_middlewares:
            reason = mw.consume_stop_reason(self.run_id)
            if reason is not None:
                return reason
        return None

    async def _load_skills(self) -> list[Skill]:
        '''按技能白名单加载已启用技能，并将磁盘读取移出事件循环。'''
        if self.config.skills is not None and len(self.config.skills) == 0:
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} skills=[] — skipping skill loading")
            return []

        try:
            from deerflow.skills.storage import get_or_new_skill_storage

            storage_kwargs = {"app_config": self.app_config} if self.app_config is not None else {}
            storage = await asyncio.to_thread(get_or_new_skill_storage, **storage_kwargs)
            # 磁盘扫描可能阻塞，因此放入线程池，避免卡住网关异步请求循环。
            all_skills = await asyncio.to_thread(storage.load_skills, enabled_only=True)
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} loaded {len(all_skills)} enabled skills from disk")
        except Exception:
            logger.exception(f"[trace={self.trace_id}] Failed to load skills for subagent {self.config.name}")
            raise

        if not all_skills:
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} no enabled skills found")
            return []

        # 若配置了技能白名单，仅向子代理提供名单中的技能。
        if self.config.skills is not None:
            allowed = set(self.config.skills)
            return [s for s in all_skills if s.name in allowed]
        return all_skills

    def _apply_skill_allowed_tools(self, skills: list[Skill]) -> list[BaseTool]:
        '''根据已加载技能声明的工具白名单进一步收窄基础工具集合。'''
        return filter_tools_by_skill_allowed_tools(self._base_tools, skills)

    async def _load_skill_messages(self, skills: list[Skill]) -> list[SystemMessage]:
        '''读取技能说明文件并转义不可信内容，再合成为代理系统消息。'''
        if not skills:
            return []

        # 每个技能说明都以独立片段读取，之后合并到代理系统提示中。
        messages = []
        for skill in skills:
            try:
                content = await asyncio.to_thread(skill.skill_file.read_text, encoding="utf-8")
                content = content.strip()
                if content:
                    # 可安装技能包是不可信输入；转义名称与正文，防止内容伪造外围技能标签。
                    messages.append(SystemMessage(content=f'<skill name="{html.escape(skill.name, quote=True)}">\n{html.escape(content, quote=False)}\n</skill>'))
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} loaded skill: {skill.name}")
            except Exception:
                logger.debug(f"[trace={self.trace_id}] Failed to read skill {skill.name}", exc_info=True)

        return messages

    async def _build_initial_state(self, task: str) -> tuple[dict[str, Any], list[BaseTool], "DeferredToolSetup"]:
        '''加载技能和延迟工具提示，合并系统消息，并继承父代理沙箱状态。'''
        # 延迟导入以避免工具包初始化期间反向导入正在初始化的 subagents 包。
        from deerflow.tools.builtins.tool_search import assemble_deferred_tools, get_deferred_tools_prompt_section, get_mcp_routing_hints_prompt_section

        # 先加载技能，再据技能策略过滤可用工具。
        skills = await self._load_skills()
        filtered_tools = self._apply_skill_allowed_tools(skills)
        # 先执行工具策略再构造延迟搜索目录；目录只含已许可工具，避免搜索绕过拒绝规则。
        enabled = (self.app_config or get_app_config()).tool_search.enabled
        final_tools, deferred_setup = assemble_deferred_tools(filtered_tools, enabled=enabled)
        skill_messages = await self._load_skill_messages(skills)

        # 将代理提示、技能说明和工具路由提示合并成一条系统消息，兼容只接受单条系统消息的模型。
        system_parts: list[str] = []
        if self.config.system_prompt:
            system_parts.append(self.config.system_prompt)
        for skill_msg in skill_messages:
            system_parts.append(skill_msg.content)
        # 只在提示中列出延迟工具名称，完整参数结构由后续工具搜索按需加载。
        deferred_section = get_deferred_tools_prompt_section(deferred_names=deferred_setup.deferred_names)
        if deferred_section:
            system_parts.append(deferred_section)
        mcp_routing_hints_section = get_mcp_routing_hints_prompt_section(filtered_tools, deferred_names=deferred_setup.deferred_names)
        if mcp_routing_hints_section:
            system_parts.append(mcp_routing_hints_section)

        messages: list[Any] = []
        if system_parts:
            messages.append(SystemMessage(content="\n\n".join(system_parts)))

        # 最后追加本次委派的实际任务内容。
        messages.append(HumanMessage(content=task))

        state: dict[str, Any] = {
            "messages": messages,
        }

        # 继承父代理已解析的沙箱和线程数据，保持子代理访问同一工作区。
        if self.sandbox_state is not None:
            state["sandbox"] = self.sandbox_state
        if self.thread_data is not None:
            state["thread_data"] = self.thread_data

        return state, final_tools, deferred_setup

    async def _aexecute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        '''运行代理并持续收集消息和令牌用量，统一处理取消、预算耗尽及异常终态。'''
        if result_holder is not None:
            # 后台任务传入共享结果对象，以便轮询接口实时观察执行进度。
            result = result_holder
        else:
            # 同步调用在此新建执行结果，返回前会将其推进到终态。
            task_id = str(uuid.uuid4())[:8]
            result = SubagentResult(
                task_id=task_id,
                trace_id=self.trace_id,
                status=SubagentStatus.RUNNING,
                started_at=datetime.now(),
            )
        ai_messages = result.ai_messages
        if ai_messages is None:
            ai_messages = []
            result.ai_messages = ai_messages
        # values 流每轮会重发完整状态；按消息 ID 去重避免反复扫描历史造成二次复杂度增长。
        seen_message_ids: set[str] = {mid for msg in ai_messages if (mid := msg.get("id"))}
        # 记录已处理消息数量，使每个流数据块只检查历史尾部的新消息。
        processed_message_count = 0

        collector: SubagentTokenCollector | None = None
        try:
            state, final_tools, deferred_setup = await self._build_initial_state(task)
            agent = self._create_agent(final_tools, deferred_setup=deferred_setup)

            # 统计子代理自身的模型调用用量，并传回主运行账本。
            collector_caller = f"subagent:{self.config.name}"
            collector = SubagentTokenCollector(caller=collector_caller)

            # 不在子调用配置中重写检查点坐标，让 LangGraph 从父运行继承子图命名空间；
            # 业务工具所需线程标识通过下方 context 传递。
            run_config: RunnableConfig = {
                "recursion_limit": self.config.max_turns,
                "callbacks": [collector],
                "tags": [collector_caller],
            }

            # 在代理图层级注入追踪回调，让节点、模型和工具调用处于同一子代理追踪下，
            # 同时避免模型层再次附加回调造成重复记录。
            tracing_callbacks = build_tracing_callbacks()
            if tracing_callbacks:
                existing_callbacks = list(run_config.get("callbacks") or [])
                run_config["callbacks"] = [*existing_callbacks, *tracing_callbacks]

            # 将名称规范为小写连字符形式，使追踪标识与主代理命名风格一致。
            if self.config.name:
                normalized_name = self.config.name.strip().lower().replace("_", "-")
                assistant_id = f"subagent:{normalized_name}"
            else:
                assistant_id = "subagent"

            # 添加线程、用户与环境元数据，使子代理追踪能关联到父线程。
            inject_langfuse_metadata(
                run_config,
                thread_id=self.thread_id,
                user_id=self.user_id,
                assistant_id=assistant_id,
                model_name=self.model_name,
                environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
                deerflow_trace_id=self.deerflow_trace_id,
            )

            context: dict[str, Any] = {}
            if self.thread_id:
                context["thread_id"] = self.thread_id
            if self.app_config is not None:
                context["app_config"] = self.app_config
            # 透传父运行的用户和授权身份，让委派工具调用沿用同一权限判定与审计归属。
            context["user_id"] = self.user_id
            context["user_role"] = self.user_role
            context["oauth_provider"] = self.oauth_provider
            context["oauth_id"] = self.oauth_id
            context["run_id"] = self.run_id
            if self.channel_user_id:
                context["channel_user_id"] = self.channel_user_id
            if self.deerflow_trace_id:
                context[DEERFLOW_TRACE_METADATA_KEY] = self.deerflow_trace_id
            context["is_subagent"] = True

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution with max_turns={self.config.max_turns}")

            # 使用流式执行以逐步收集助手消息和工具输出。
            final_state = None

            # 若流式执行尚未开始就已收到取消请求，则直接结束任务。
            if result.cancel_event.is_set():
                logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} cancelled before streaming")
                result.try_set_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    token_usage_records=collector.snapshot_records(),
                )
                return result

            async for chunk in agent.astream(state, config=run_config, context=context, stream_mode="values"):  # type: ignore[arg-type]
                # 在流数据块边界检查父运行的协作式取消；单个长工具调用需等到下个数据块才会响应。
                if result.cancel_event.is_set():
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} cancelled by parent")
                    result.try_set_terminal(
                        SubagentStatus.CANCELLED,
                        error="Cancelled by user",
                        token_usage_records=collector.snapshot_records(),
                    )
                    return result

                final_state = chunk
                result.update_token_usage_records(collector.snapshot_records())

                # 捕获上次处理后新增的全部消息；一次模型轮次可能产生多条工具结果，不能只取末条。
                messages = chunk.get("messages", [])
                previous_count = len(ai_messages)
                processed_message_count = capture_new_step_messages(messages, ai_messages, seen_message_ids, processed_message_count)
                if len(ai_messages) > previous_count:
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} captured {len(ai_messages) - previous_count} step message(s); total #{len(ai_messages)}")

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed async execution")
            token_usage_records = collector.snapshot_records()
            llm_error = _extract_llm_error_fallback(final_state)
            if llm_error is not None:
                result.try_set_terminal(
                    SubagentStatus.FAILED,
                    error=llm_error,
                    token_usage_records=token_usage_records,
                )
            else:
                final_result = _extract_final_result(final_state, trace_id=self.trace_id, name=self.config.name)
                # 预算或循环保护会移除工具调用并让模型给出最终答案；消费保护器原因后，
                # 将触发原因附在成功结果上供主代理识别。
                stop_reason = self._consume_guard_stop_reason()
                result.try_set_terminal(
                    SubagentStatus.COMPLETED,
                    result=final_result,
                    stop_reason=stop_reason,
                    token_usage_records=token_usage_records,
                )

        except GraphRecursionError:
            # 达到 LangGraph 递归上限即耗尽轮数预算。若已有可用部分结果则保留为 completed，
            # 否则标记 failed，并通过附加停止原因保持状态枚举兼容。若令牌或循环保护已触发，
            # 则优先报告该限制，因为它可能先于轮数上限约束本次运行。
            max_turns = self.config.max_turns
            logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} reached max_turns={max_turns} (GraphRecursionError); recovering partial result")
            records = collector.snapshot_records() if collector is not None else None
            stop_reason = self._consume_guard_stop_reason() or "turn_capped"

            # 模型供应商错误也可能在终态消息中带有文本；先检查错误标记，避免把错误提示
            # 误当成成功的部分结果。
            llm_error = _extract_llm_error_fallback(final_state)
            if llm_error is not None:
                result.try_set_terminal(
                    SubagentStatus.FAILED,
                    error=llm_error,
                    stop_reason=stop_reason,
                    token_usage_records=records,
                )
            else:
                messages = (final_state or {}).get("messages", [])
                usable_partial: str | None = None
                for m in reversed(messages):
                    if isinstance(m, AIMessage):
                        text = message_content_to_text(m.content).strip()
                        if text:
                            usable_partial = text
                        break
                if usable_partial is not None:
                    result.try_set_terminal(
                        SubagentStatus.COMPLETED,
                        result=usable_partial,
                        stop_reason=stop_reason,
                        token_usage_records=records,
                    )
                else:
                    result.try_set_terminal(
                        SubagentStatus.FAILED,
                        error=f"Reached max_turns={max_turns}",
                        stop_reason=stop_reason,
                        token_usage_records=records,
                    )

        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
            result.try_set_terminal(
                SubagentStatus.FAILED,
                error=str(e),
                token_usage_records=collector.snapshot_records() if collector is not None else None,
            )

        return result

    def _execute_in_isolated_loop(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        '''将同步调用提交到常驻隔离事件循环，并按代理超时限制等待结果。'''
        future: Future[SubagentResult] | None = None
        parent_context = copy_context()
        try:
            future = _submit_to_isolated_loop_in_context(
                parent_context,
                lambda: self._aexecute(task, result_holder),
            )
            return future.result(timeout=self.config.timeout_seconds)
        except FuturesTimeoutError:
            if result_holder is not None:
                result_holder.cancel_event.set()
            if future is not None:
                future.cancel()
            raise
        except Exception:
            if future is None:
                logger.debug(
                    f"[trace={self.trace_id}] Failed to submit subagent {self.config.name} to the isolated event loop",
                    exc_info=True,
                )
            else:
                logger.debug(
                    f"[trace={self.trace_id}] Subagent {self.config.name} failed while executing on the isolated event loop",
                    exc_info=True,
                )
            raise

    def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        '''根据调用线程是否已有事件循环选择安全执行路径，并把异常转换为失败结果。'''
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                logger.debug(f"[trace={self.trace_id}] Subagent {self.config.name} detected running event loop, using isolated loop")
                return self._execute_in_isolated_loop(task, result_holder)

            # 当前线程没有运行中的事件循环时，直接通过 asyncio.run 执行。
            return asyncio.run(self._aexecute(task, result_holder))
        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed")
            # 若调用方未提供共享结果对象，则创建一条可返回的失败结果。
            if result_holder is not None:
                result = result_holder
            else:
                result = SubagentResult(
                    task_id=str(uuid.uuid4())[:8],
                    trace_id=self.trace_id,
                    status=SubagentStatus.RUNNING,
                )
            result.try_set_terminal(SubagentStatus.FAILED, error=str(e))
            return result

    def execute_async(self, task: str, task_id: str | None = None) -> str:
        '''登记待执行任务并在线程池后台启动子代理，立即返回任务标识供轮询。'''
        # 优先沿用调用方生成的任务标识，否则创建新的短标识。
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        # 先登记排队状态，供状态查询接口立即读取。
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
        )

        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution, task_id={task_id}, timeout={self.config.timeout_seconds}s")

        with _background_tasks_lock:
            _background_tasks[task_id] = result

        parent_context = copy_context()

        # 调度线程负责切换运行状态、等待异步任务并处理超时。
        def run_task():
            '''在调度线程中标记后台任务开始，提交隔离执行并处理超时和异常。'''
            with _background_tasks_lock:
                _background_tasks[task_id].status = SubagentStatus.RUNNING
                _background_tasks[task_id].started_at = datetime.now()
                result_holder = _background_tasks[task_id]

            try:
                # 直接提交到常驻隔离循环，避免后台执行路径重复创建临时循环。
                execution_future = _submit_to_isolated_loop_in_context(
                    parent_context,
                    lambda: self._aexecute(task, result_holder),
                )
                try:
                    # 等待任务完成，超过代理配置的上限则触发协作式取消。
                    execution_future.result(timeout=self.config.timeout_seconds)
                except FuturesTimeoutError:
                    logger.error(f"[trace={self.trace_id}] Subagent {self.config.name} execution timed out after {self.config.timeout_seconds}s")
                    # 通知运行中的代理停止，并取消尚未完成的调度任务。
                    result_holder.cancel_event.set()
                    result_holder.try_set_terminal(
                        SubagentStatus.TIMED_OUT,
                        error=f"Execution timed out after {self.config.timeout_seconds} seconds",
                    )
                    execution_future.cancel()
            except Exception as e:
                logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
                with _background_tasks_lock:
                    task_result = _background_tasks[task_id]
                task_result.try_set_terminal(SubagentStatus.FAILED, error=str(e))

        _scheduler_pool.submit(run_task)
        return task_id


MAX_CONCURRENT_SUBAGENTS = 3


def request_cancel_background_task(task_id: str) -> None:
    '''请求后台任务尽快取消；具体停止时机取决于当前模型或工具调用是否让出控制权。'''
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result is not None:
            result.cancel_event.set()
            logger.info("Requested cancellation for background task %s", task_id)


def get_background_task_result(task_id: str) -> SubagentResult | None:
    '''按任务标识读取后台任务结果，不存在时返回空值。'''
    with _background_tasks_lock:
        return _background_tasks.get(task_id)


def list_background_tasks() -> list[SubagentResult]:
    '''返回当前进程所有后台子代理结果的列表快照。'''
    with _background_tasks_lock:
        return list(_background_tasks.values())


def cleanup_background_task(task_id: str) -> None:
    '''仅删除已进入终态的后台记录，避免与仍在运行的任务发生竞争。'''
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result is None:
            # 记录可能已被其他清理操作移除，无需重复处理。
            logger.debug("Requested cleanup for unknown background task %s", task_id)
            return

        # 运行中的执行器仍会更新结果对象，因此只允许清理已经进入终态的记录。
        if result.status.is_terminal or result.completed_at is not None:
            del _background_tasks[task_id]
            logger.debug("Cleaned up background task: %s", task_id)
        else:
            logger.debug(
                "Skipping cleanup for non-terminal background task %s (status=%s)",
                task_id,
                result.status.value if hasattr(result.status, "value") else result.status,
            )
