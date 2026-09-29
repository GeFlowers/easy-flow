"""提供鹿流的嵌入式客户端。

本模块不经由网络网关，直接在当前进程内创建并调用智能体；同时提供会话、目标、
模型、技能、记忆、上传文件与产物的网关等价操作。同步调用会在必要时桥接异步
实现，流式调用逐条产出事件对象；不会创建等待或异步流等额外接口，也不会改变
既有调用语义。
"""

import asyncio
import concurrent.futures
import json
import logging
import mimetypes
import os
import shutil
import tempfile
import uuid
from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.lead_agent.prompt import apply_prompt_template, get_enabled_skills_for_config
from deerflow.agents.thread_state import ThreadState
from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.config.app_config import get_app_config, is_trace_correlation_enabled, reload_app_config
from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from deerflow.config.paths import get_paths
from deerflow.models import create_chat_model
from deerflow.runtime.goal import DEFAULT_MAX_GOAL_CONTINUATIONS, build_goal_state, goal_thread_lock, read_thread_goal, write_thread_goal
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.skills.describe import build_skill_search_setup
from deerflow.skills.storage import get_or_new_user_skill_storage
from deerflow.tools.builtins.tool_search import assemble_deferred_tools, build_mcp_routing_middleware, get_mcp_routing_hints_prompt_section
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, generate_trace_id, get_current_trace_id, reset_current_trace_id, set_current_trace_id
from deerflow.tracing import build_tracing_callbacks, inject_langfuse_metadata
from deerflow.uploads.manager import (
    claim_unique_filename,
    delete_file_safe,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    upload_artifact_url,
    upload_virtual_path,
)

logger = logging.getLogger(__name__)


def _run_async_from_sync(coro):
    """在同步客户端入口安全执行协程并返回结果。

    若调用方不在运行中的事件循环内，直接运行协程；若已处于事件循环，便在
    独立单线程中创建临时事件循环执行，避免同步等待阻塞或嵌套当前循环。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


StreamEventType = Literal["values", "messages-tuple", "custom", "end"]


@dataclass
class StreamEvent:
    """表示一次嵌入式智能体流式响应事件。

    类型与网关流协议保持一致：状态快照、消息增量、图写入的自定义载荷和结束事件
    各有不同数据字段；结束事件还携带累计用量。
    """

    type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)


class DeerFlowClient:
    """在同一进程内访问鹿流全部核心能力的客户端。

    智能体按配置惰性创建并缓存；配置、技能或记忆改变后可重置缓存。多轮对话
    依赖检查点保存线程状态；没有检查点时，线程标识仍用于隔离上传文件和产物，
    但不会保留聊天上下文。流式方法是同步迭代器，便捷对话方法负责聚合其文本增量。
    """

    def __init__(
        self,
        config_path: str | None = None,
        checkpointer=None,
        *,
        model_name: str | None = None,
        thinking_enabled: bool = True,
        subagent_enabled: bool = False,
        plan_mode: bool = False,
        agent_name: str | None = None,
        available_skills: set[str] | None = None,
        middlewares: Sequence[AgentMiddleware] | None = None,
        environment: str | None = None,
    ):
        """初始化客户端配置与惰性创建所需的依赖。

        配置路径可替换配置来源；检查点决定同一线程是否持久化。
        其余参数覆盖模型、思考、子智能体、计划模式、可用技能及中间件；部署环境
        标签未给定时从环境变量读取。
        """
        if config_path is not None:
            reload_app_config(config_path)
        self._app_config = get_app_config()

        if agent_name is not None and not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name '{agent_name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")

        self._checkpointer = checkpointer
        self._model_name = model_name
        self._thinking_enabled = thinking_enabled
        self._subagent_enabled = subagent_enabled
        self._plan_mode = plan_mode
        self._agent_name = agent_name
        self._available_skills = set(available_skills) if available_skills is not None else None
        self._middlewares = list(middlewares) if middlewares else []
        self._environment = environment

        # Lazy agent — created on first call, recreated when config changes.
        self._agent = None
        self._agent_config_key: tuple | None = None

    def reset_agent(self) -> None:
        """清除已缓存的智能体，使下一次调用按最新配置重建。

        当记忆、技能或外部配置变化且需影响系统提示词或工具集时调用本方法。
        """
        self._agent = None
        self._agent_config_key = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _atomic_write_json(path: Path, data: dict) -> None:
        """将字典先写入同目录临时文件，再原子替换目标数据文件。"""
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        )
        try:
            json.dump(data, fd, indent=2)
            fd.close()
            Path(fd.name).replace(path)
        except BaseException:
            fd.close()
            Path(fd.name).unlink(missing_ok=True)
            raise

    def _get_runnable_config(self, thread_id: str, **overrides) -> RunnableConfig:
        """根据线程标识和单次覆盖参数构造智能体运行配置。"""
        configurable = {
            "thread_id": thread_id,
            "model_name": overrides.get("model_name", self._model_name),
            "thinking_enabled": overrides.get("thinking_enabled", self._thinking_enabled),
            "is_plan_mode": overrides.get("plan_mode", self._plan_mode),
            "subagent_enabled": overrides.get("subagent_enabled", self._subagent_enabled),
        }
        return RunnableConfig(
            configurable=configurable,
            recursion_limit=overrides.get("recursion_limit", 100),
        )

    def _ensure_agent(self, config: RunnableConfig):
        """在模型与功能配置变化时创建或重建缓存的智能体。"""
        cfg = config.get("configurable", {})
        key = (
            cfg.get("model_name"),
            cfg.get("thinking_enabled"),
            cfg.get("is_plan_mode"),
            cfg.get("subagent_enabled"),
            cfg.get("max_concurrent_subagents"),
            cfg.get("max_total_subagents"),
            self._agent_name,
            frozenset(self._available_skills) if self._available_skills is not None else None,
        )

        if self._agent is not None and self._agent_config_key == key:
            return

        thinking_enabled = cfg.get("thinking_enabled", True)
        model_name = cfg.get("model_name")
        subagent_enabled = cfg.get("subagent_enabled", False)
        max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
        max_total_subagents = cfg.get("max_total_subagents", self._app_config.subagents.max_total_per_run)

        tools = self._get_tools(model_name=model_name, subagent_enabled=subagent_enabled)
        final_tools, deferred_setup = assemble_deferred_tools(tools, enabled=self._app_config.tool_search.enabled)
        mcp_routing_middleware = build_mcp_routing_middleware(
            final_tools,
            deferred_setup,
            top_k=self._app_config.tool_search.auto_promote_top_k,
        )
        mcp_routing_hints_section = get_mcp_routing_hints_prompt_section(tools, deferred_names=deferred_setup.deferred_names)

        # Wire deferred skill discovery — mirrors agent.py so config flag works on both paths.
        skills_list = get_enabled_skills_for_config(self._app_config)
        if self._available_skills is not None:
            skills_list = [s for s in skills_list if s.name in self._available_skills]
        skill_setup = build_skill_search_setup(
            skills_list,
            enabled=self._app_config.skills.deferred_discovery,
            container_base_path=self._app_config.skills.container_path,
        )
        if skill_setup.describe_skill_tool:
            final_tools.append(skill_setup.describe_skill_tool)

        kwargs: dict[str, Any] = {
            # attach_tracing=False because ``stream()`` injects tracing
            # callbacks at the graph invocation root so a single embedded run
            # produces one trace with correct session_id / user_id propagation.
            # Attaching them again on the model would emit duplicate spans.
            "model": create_chat_model(name=model_name, thinking_enabled=thinking_enabled, attach_tracing=False),
            "tools": final_tools,
            "middleware": build_middlewares(
                config,
                model_name=model_name,
                agent_name=self._agent_name,
                available_skills=self._available_skills,
                custom_middlewares=self._middlewares,
                app_config=self._app_config,
                deferred_setup=deferred_setup,
                mcp_routing_middleware=mcp_routing_middleware,
                user_id=get_effective_user_id(),
            ),
            "system_prompt": apply_prompt_template(
                subagent_enabled=subagent_enabled,
                max_concurrent_subagents=max_concurrent_subagents,
                max_total_subagents=max_total_subagents,
                agent_name=self._agent_name,
                available_skills=self._available_skills,
                app_config=self._app_config,
                deferred_names=deferred_setup.deferred_names,
                mcp_routing_hints_section=mcp_routing_hints_section,
                user_id=get_effective_user_id(),
                skill_names=skill_setup.skill_names or None,
            ),
            "state_schema": ThreadState,
        }
        checkpointer = self._checkpointer
        if checkpointer is None:
            from deerflow.runtime.checkpointer import get_checkpointer

            checkpointer = get_checkpointer()
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer

        self._agent = create_agent(**kwargs)
        self._agent_config_key = key
        logger.info("Agent created: agent_name=%s, model=%s, thinking=%s", self._agent_name, model_name, thinking_enabled)

    @staticmethod
    def _get_tools(*, model_name: str | None, subagent_enabled: bool):
        """延迟导入并返回当前模型和子智能体设置可用的工具，避免循环依赖。"""
        from deerflow.tools import get_available_tools

        return get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled)

    @staticmethod
    def _serialize_tool_calls(tool_calls) -> list[dict]:
        """将工具调用转换为流事件使用的名称、参数和标识字典。"""
        return [{"name": tc["name"], "args": tc["args"], "id": tc.get("id")} for tc in tool_calls]

    @staticmethod
    def _serialize_additional_kwargs(msg) -> dict[str, Any] | None:
        """在消息携带附加参数时复制其字典，避免事件引用原始对象。"""
        additional_kwargs = getattr(msg, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict) and additional_kwargs:
            return dict(additional_kwargs)
        return None

    @staticmethod
    def _ai_text_event(msg_id: str | None, text: str, usage: dict | None, additional_kwargs: dict[str, Any] | None = None) -> "StreamEvent":
        """构造包含文本增量、用量与附加参数的 AI 消息流事件。"""
        data: dict[str, Any] = {"type": "ai", "content": text, "id": msg_id}
        if usage:
            data["usage_metadata"] = usage
        if additional_kwargs:
            data["additional_kwargs"] = additional_kwargs
        return StreamEvent(type="messages-tuple", data=data)

    @staticmethod
    def _ai_tool_calls_event(msg_id: str | None, tool_calls, additional_kwargs: dict[str, Any] | None = None) -> "StreamEvent":
        """构造包含 AI 工具调用列表的消息流事件。"""
        data: dict[str, Any] = {
            "type": "ai",
            "content": "",
            "id": msg_id,
            "tool_calls": DeerFlowClient._serialize_tool_calls(tool_calls),
        }
        if additional_kwargs:
            data["additional_kwargs"] = additional_kwargs
        return StreamEvent(type="messages-tuple", data=data)

    @staticmethod
    def _tool_message_event(msg: ToolMessage) -> "StreamEvent":
        """将工具结果消息转换为包含调用关联标识的流事件。"""
        return StreamEvent(
            type="messages-tuple",
            data={
                "type": "tool",
                "content": DeerFlowClient._extract_text(msg.content),
                "name": msg.name,
                "tool_call_id": msg.tool_call_id,
                "id": msg.id,
            },
        )

    @staticmethod
    def _serialize_message(msg) -> dict:
        """将各类框架消息序列化为状态快照中的普通字典。"""
        if isinstance(msg, AIMessage):
            d: dict[str, Any] = {"type": "ai", "content": msg.content, "id": getattr(msg, "id", None)}
            if msg.tool_calls:
                d["tool_calls"] = DeerFlowClient._serialize_tool_calls(msg.tool_calls)
            if getattr(msg, "usage_metadata", None):
                d["usage_metadata"] = msg.usage_metadata
            if additional_kwargs := DeerFlowClient._serialize_additional_kwargs(msg):
                d["additional_kwargs"] = additional_kwargs
            return d
        if isinstance(msg, ToolMessage):
            d = {
                "type": "tool",
                "content": DeerFlowClient._extract_text(msg.content),
                "name": getattr(msg, "name", None),
                "tool_call_id": getattr(msg, "tool_call_id", None),
                "id": getattr(msg, "id", None),
            }
            if additional_kwargs := DeerFlowClient._serialize_additional_kwargs(msg):
                d["additional_kwargs"] = additional_kwargs
            return d
        if isinstance(msg, HumanMessage):
            d = {"type": "human", "content": msg.content, "id": getattr(msg, "id", None)}
            if additional_kwargs := DeerFlowClient._serialize_additional_kwargs(msg):
                d["additional_kwargs"] = additional_kwargs
            return d
        if isinstance(msg, SystemMessage):
            d = {"type": "system", "content": msg.content, "id": getattr(msg, "id", None)}
            if additional_kwargs := DeerFlowClient._serialize_additional_kwargs(msg):
                d["additional_kwargs"] = additional_kwargs
            return d
        return {"type": "unknown", "content": str(msg), "id": getattr(msg, "id", None)}

    @staticmethod
    def _extract_text(content) -> str:
        """从字符串或内容块列表中提取可展示的纯文本。

        连续短字符串块会直接拼接，以保留令牌增量和分片结构化数据；字典文本块按换行
        合并，以维持完整段落的可读性。
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            if content and all(isinstance(block, str) for block in content):
                chunk_like = len(content) > 1 and all(isinstance(block, str) and len(block) <= 20 and any(ch in block for ch in '{}[]":,') for block in content)
                return "".join(content) if chunk_like else "\n".join(content)

            pieces: list[str] = []
            pending_str_parts: list[str] = []

            def flush_pending_str_parts() -> None:
                """将暂存的连续字符串块合并为一个文本片段。"""
                if pending_str_parts:
                    pieces.append("".join(pending_str_parts))
                    pending_str_parts.clear()

            for block in content:
                if isinstance(block, str):
                    pending_str_parts.append(block)
                elif isinstance(block, dict):
                    flush_pending_str_parts()
                    text_val = block.get("text")
                    if isinstance(text_val, str):
                        pieces.append(text_val)

            flush_pending_str_parts()
            return "\n".join(pieces) if pieces else ""
        return str(content)

    # ------------------------------------------------------------------
    # Public API — threads
    # ------------------------------------------------------------------

    def _get_thread_checkpointer(self):
        """返回显式注入或按当前配置解析出的线程检查点存储。"""
        checkpointer = self._checkpointer
        if checkpointer is None:
            from deerflow.runtime.checkpointer.provider import get_checkpointer

            checkpointer = get_checkpointer()
        return checkpointer

    def get_goal(self, thread_id: str) -> dict:
        """读取线程当前目标；目标不存在时返回空目标结果。"""
        checkpointer = self._get_thread_checkpointer()
        goal = _run_async_from_sync(read_thread_goal(checkpointer, thread_id))
        return {"goal": goal}

    def set_goal(
        self,
        thread_id: str,
        objective: str,
        *,
        max_continuations: int = DEFAULT_MAX_GOAL_CONTINUATIONS,
    ) -> dict:
        """为线程创建或替换目标，并在异步锁内持久化其续写上限。"""
        checkpointer = self._get_thread_checkpointer()
        goal = build_goal_state(objective, max_continuations=max_continuations)

        async def _set_goal() -> None:
            """串行写入当前线程目标，避免与其他目标操作竞争。"""
            async with goal_thread_lock(thread_id):
                await write_thread_goal(checkpointer, thread_id, goal, create_if_missing=True)

        _run_async_from_sync(_set_goal())
        return {"goal": goal}

    def clear_goal(self, thread_id: str) -> dict:
        """清除线程目标；线程尚无检查点时也将其视为已清除。"""
        checkpointer = self._get_thread_checkpointer()

        async def _clear_goal() -> None:
            """在目标锁保护下将线程目标写为空值。"""
            async with goal_thread_lock(thread_id):
                await write_thread_goal(checkpointer, thread_id, None)

        try:
            _run_async_from_sync(_clear_goal())
        except LookupError:
            pass
        return {"goal": None}

    def list_threads(self, limit: int = 10) -> dict:
        """列出最近创建的线程及其首末检查点、标题和时间信息。

        数量上限限制返回数量；遍历不同命名空间的检查点后会按创建时间倒序排序。
        """
        checkpointer = self._get_thread_checkpointer()

        thread_info_map = {}

        for cp in checkpointer.list(config=None, limit=limit):
            cfg = cp.config.get("configurable", {})
            thread_id = cfg.get("thread_id")
            if not thread_id:
                continue

            ts = cp.checkpoint.get("ts")
            checkpoint_id = cfg.get("checkpoint_id")

            if thread_id not in thread_info_map:
                channel_values = cp.checkpoint.get("channel_values", {})
                thread_info_map[thread_id] = {
                    "thread_id": thread_id,
                    "created_at": ts,
                    "updated_at": ts,
                    "latest_checkpoint_id": checkpoint_id,
                    "title": channel_values.get("title"),
                }
            else:
                # Explicitly compare timestamps to ensure accuracy when iterating over unordered namespaces.
                # Treat None as "missing" and only compare when existing values are non-None.
                if ts is not None:
                    current_created = thread_info_map[thread_id]["created_at"]
                    if current_created is None or ts < current_created:
                        thread_info_map[thread_id]["created_at"] = ts

                    current_updated = thread_info_map[thread_id]["updated_at"]
                    if current_updated is None or ts > current_updated:
                        thread_info_map[thread_id]["updated_at"] = ts
                        thread_info_map[thread_id]["latest_checkpoint_id"] = checkpoint_id
                        channel_values = cp.checkpoint.get("channel_values", {})
                        thread_info_map[thread_id]["title"] = channel_values.get("title")

        threads = list(thread_info_map.values())
        threads.sort(key=lambda x: x.get("created_at") or "", reverse=True)

        return {"thread_list": threads[:limit]}

    def get_thread(self, thread_id: str) -> dict:
        """读取一个线程的完整检查点历史与节点写入记录。

        返回值中的消息会转为普通字典，检查点按时间升序排列，便于调用方重放状态。
        """
        checkpointer = self._get_thread_checkpointer()

        config = {"configurable": {"thread_id": thread_id}}
        checkpoints = []

        for cp in checkpointer.list(config):
            channel_values = dict(cp.checkpoint.get("channel_values", {}))
            if "messages" in channel_values:
                channel_values["messages"] = [self._serialize_message(m) if hasattr(m, "content") else m for m in channel_values["messages"]]

            cfg = cp.config.get("configurable", {})
            parent_cfg = cp.parent_config.get("configurable", {}) if cp.parent_config else {}

            checkpoints.append(
                {
                    "checkpoint_id": cfg.get("checkpoint_id"),
                    "parent_checkpoint_id": parent_cfg.get("checkpoint_id"),
                    "ts": cp.checkpoint.get("ts"),
                    "metadata": cp.metadata,
                    "values": channel_values,
                    "pending_writes": [{"task_id": w[0], "channel": w[1], "value": w[2]} for w in getattr(cp, "pending_writes", [])],
                }
            )

        # Sort globally by timestamp to prevent partial ordering issues caused by different namespaces (e.g., subgraphs)
        checkpoints.sort(key=lambda x: x["ts"] if x["ts"] else "")

        return {"thread_id": thread_id, "checkpoints": checkpoints}

    # ------------------------------------------------------------------
    # Public API — conversation
    # ------------------------------------------------------------------

    def stream(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        **kwargs,
    ) -> Generator[StreamEvent, None, None]:
        """以同步生成器流式执行一轮对话，并逐条返回事件对象。

        该接口使用底层同步图流，不是协程，也不提供等待或异步流包装；调用方应直接
        迭代。开启日志关联时，每次推进内部生成器前
        都绑定并在产出前复位追踪标识，既让图执行和日志继承同一标识，也不会把
        上下文变量泄漏给调用方或在跨上下文关闭生成器时出错。关闭关联时仅继承
        调用方主动绑定的标识，不会自动创建新的请求标识。
        """
        if not is_trace_correlation_enabled(self._app_config):
            yield from self._stream_without_trace_context(message, thread_id=thread_id, **kwargs)
            return

        # Resolve the trace id once, without mutating the caller's context.
        # Inherits an ambient id if the caller opted in via
        # ``request_trace_context``; otherwise mints a fresh one.
        trace_id = get_current_trace_id() or generate_trace_id()

        # Bind the trace id only around each ``next()`` step, never across a
        # ``yield``. ``stream()`` is a sync generator, which shares the
        # caller's context — a ``with ensure_trace_context(): yield from ...``
        # would (1) leak the id into the caller's context between yields and
        # (2) risk ``ValueError: Token was created in a different Context``
        # when GC finalizes an abandoned generator in a different context.
        # Per-step set/reset keeps LangGraph node execution and its log
        # records inside the binding while returning control to the caller
        # with the ContextVar restored.
        inner = self._stream_without_trace_context(message, thread_id=thread_id, **kwargs)
        _EXHAUSTED = object()
        try:
            while True:
                token = set_current_trace_id(trace_id)
                try:
                    try:
                        event = next(inner)
                    except StopIteration:
                        event = _EXHAUSTED
                finally:
                    reset_current_trace_id(token)
                if event is _EXHAUSTED:
                    break
                yield event
        finally:
            inner.close()

    def _stream_without_trace_context(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        **kwargs,
    ) -> Generator[StreamEvent, None, None]:
        """实际订阅图的同步流，并将一轮对话转换为嵌入式事件。

        未传线程标识时自动生成；传入检查点后同一线程可续接上下文。它同步订阅
        状态快照、消息增量、自定义载荷三种图流：人工智能文本以带稳定消息标识的
        增量产出，调用方需按标识拼接；工具调用和结果各产出一次；状态快照不会重复
        发送已由消息流发送的人工智能文本；结束事件携带按消息去重后的累计令牌用量。

        网关运行器使用异步图流并经队列、事件流序列化、
        重放和心跳服务网络订阅者；本方法直接调用同步图流并交付
        原生字典，避免为单个进程内迭代器创建事件循环和线程。因此两者是共享
        智能体工厂的平行路径，不互相包装。便捷对话方法已为仅需最终文本的同步调用方
        完成增量拼接。
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        config = self._get_runnable_config(thread_id, **kwargs)

        # Inject tracing callbacks and Langfuse trace metadata at the graph
        # invocation root so the embedded client matches the gateway worker's
        # behaviour: a single ``stream()`` produces one trace with all node /
        # LLM / tool calls nested under it, and the trace carries the reserved
        # ``langfuse_session_id`` / ``langfuse_user_id`` keys that the Langfuse
        # CallbackHandler lifts onto the root trace's ``sessionId`` / ``userId``.
        tracing_callbacks = build_tracing_callbacks()
        if tracing_callbacks:
            existing_callbacks = list(config.get("callbacks") or [])
            config["callbacks"] = [*existing_callbacks, *tracing_callbacks]

        configurable = config.get("configurable") or {}
        deerflow_trace_id = get_current_trace_id()
        inject_langfuse_metadata(
            config,
            thread_id=thread_id,
            user_id=get_effective_user_id(),
            assistant_id=self._agent_name or "lead-agent",
            model_name=configurable.get("model_name") or self._model_name,
            environment=self._environment or os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
            deerflow_trace_id=deerflow_trace_id,
        )

        self._ensure_agent(config)

        run_id = str(uuid.uuid4())
        state: dict[str, Any] = {"messages": [HumanMessage(content=message, additional_kwargs={"run_id": run_id})]}
        context = {"thread_id": thread_id, "run_id": run_id}
        if deerflow_trace_id:
            context[DEERFLOW_TRACE_METADATA_KEY] = deerflow_trace_id
        if self._agent_name:
            context["agent_name"] = self._agent_name

        seen_ids: set[str] = set()
        # Cross-mode handoff: ids already streamed via LangGraph ``messages``
        # mode so the ``values`` path skips re-synthesis of the same message.
        streamed_ids: set[str] = set()
        # The same message id carries identical cumulative ``usage_metadata``
        # in both the final ``messages`` chunk and the values snapshot —
        # count it only on whichever arrives first.
        counted_usage_ids: set[str] = set()
        sent_additional_kwargs_by_id: dict[str, dict[str, Any]] = {}
        cumulative_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        def _account_usage(msg_id: str | None, usage: Any) -> dict | None:
            """仅首次遇到某消息标识时计入用量，并返回规范化后的用量字典。"""
            if not usage:
                return None
            if msg_id and msg_id in counted_usage_ids:
                return None
            if msg_id:
                counted_usage_ids.add(msg_id)
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            total_tokens = usage.get("total_tokens", 0) or 0
            cumulative_usage["input_tokens"] += input_tokens
            cumulative_usage["output_tokens"] += output_tokens
            cumulative_usage["total_tokens"] += total_tokens
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }

        def _unsent_additional_kwargs(msg_id: str | None, additional_kwargs: dict[str, Any] | None) -> dict[str, Any] | None:
            """返回尚未随同一消息标识发送过的附加参数增量。"""
            if not additional_kwargs:
                return None
            if not msg_id:
                return additional_kwargs

            sent = sent_additional_kwargs_by_id.setdefault(msg_id, {})
            delta = {key: value for key, value in additional_kwargs.items() if sent.get(key) != value}
            if not delta:
                return None

            sent.update(delta)
            return delta

        for item in self._agent.stream(
            state,
            config=config,
            context=context,
            stream_mode=["values", "messages", "custom"],
        ):
            if isinstance(item, tuple) and len(item) == 2:
                mode, chunk = item
                mode = str(mode)
            else:
                mode, chunk = "values", item

            if mode == "custom":
                yield StreamEvent(type="custom", data=chunk)
                continue

            if mode == "messages":
                # LangGraph ``messages`` mode emits ``(message_chunk, metadata)``.
                if isinstance(chunk, tuple) and len(chunk) == 2:
                    msg_chunk, _metadata = chunk
                else:
                    msg_chunk = chunk

                msg_id = getattr(msg_chunk, "id", None)

                if isinstance(msg_chunk, AIMessage):
                    text = self._extract_text(msg_chunk.content)
                    additional_kwargs = self._serialize_additional_kwargs(msg_chunk)
                    counted_usage = _account_usage(msg_id, msg_chunk.usage_metadata)
                    sent_additional_kwargs = False

                    if text:
                        if msg_id:
                            streamed_ids.add(msg_id)
                        additional_kwargs_delta = _unsent_additional_kwargs(msg_id, additional_kwargs)
                        yield self._ai_text_event(
                            msg_id,
                            text,
                            counted_usage,
                            additional_kwargs_delta,
                        )
                        sent_additional_kwargs = bool(additional_kwargs_delta)

                    if msg_chunk.tool_calls:
                        if msg_id:
                            streamed_ids.add(msg_id)
                        additional_kwargs_delta = None if sent_additional_kwargs else _unsent_additional_kwargs(msg_id, additional_kwargs)
                        yield self._ai_tool_calls_event(
                            msg_id,
                            msg_chunk.tool_calls,
                            additional_kwargs_delta,
                        )

                elif isinstance(msg_chunk, ToolMessage):
                    if msg_id:
                        streamed_ids.add(msg_id)
                    yield self._tool_message_event(msg_chunk)
                continue

            # mode == "values"
            messages = chunk.get("messages", [])

            for msg in messages:
                msg_id = getattr(msg, "id", None)
                if msg_id and msg_id in seen_ids:
                    continue
                if msg_id:
                    seen_ids.add(msg_id)

                # Already streamed via ``messages`` mode; only (defensively)
                # capture usage here and skip re-synthesizing the event.
                if msg_id and msg_id in streamed_ids:
                    if isinstance(msg, AIMessage):
                        _account_usage(msg_id, getattr(msg, "usage_metadata", None))
                        additional_kwargs = self._serialize_additional_kwargs(msg)
                        additional_kwargs_delta = _unsent_additional_kwargs(msg_id, additional_kwargs)
                        if additional_kwargs_delta:
                            # Metadata-only follow-up: ``messages-tuple`` has no
                            # dedicated attribution event, so clients should
                            # merge this empty-content AI event by message id
                            # and ignore it for text rendering.
                            yield self._ai_text_event(msg_id, "", None, additional_kwargs_delta)
                    continue

                if isinstance(msg, AIMessage):
                    counted_usage = _account_usage(msg_id, msg.usage_metadata)
                    additional_kwargs = self._serialize_additional_kwargs(msg)
                    sent_additional_kwargs = False

                    if msg.tool_calls:
                        additional_kwargs_delta = _unsent_additional_kwargs(msg_id, additional_kwargs)
                        yield self._ai_tool_calls_event(
                            msg_id,
                            msg.tool_calls,
                            additional_kwargs_delta,
                        )
                        sent_additional_kwargs = bool(additional_kwargs_delta)

                    text = self._extract_text(msg.content)
                    if text:
                        additional_kwargs_delta = None if sent_additional_kwargs else _unsent_additional_kwargs(msg_id, additional_kwargs)
                        yield self._ai_text_event(
                            msg_id,
                            text,
                            counted_usage,
                            additional_kwargs_delta,
                        )
                    elif msg_id:
                        additional_kwargs_delta = None if sent_additional_kwargs else _unsent_additional_kwargs(msg_id, additional_kwargs)
                        if not additional_kwargs_delta:
                            continue
                        # See the metadata-only follow-up convention above.
                        yield self._ai_text_event(msg_id, "", None, additional_kwargs_delta)

                elif isinstance(msg, ToolMessage):
                    yield self._tool_message_event(msg)

            # Emit a values event for each state snapshot
            yield StreamEvent(
                type="values",
                data={
                    "title": chunk.get("title"),
                    "messages": [self._serialize_message(m) for m in messages],
                    "artifacts": chunk.get("artifacts", []),
                },
            )

        yield StreamEvent(type="end", data={"usage": cumulative_usage})

    def chat(self, message: str, *, thread_id: str | None = None, **kwargs) -> str:
        """发送消息并返回最后一个人工智能消息拼接后的完整文本。

        本方法同步遍历流式方法，按消息标识收集文本增量并忽略中间草稿；若要获得
        工具事件、状态快照或每个文本片段，应直接迭代流式方法。
        """
        # Per-id delta lists joined once at the end — avoids the O(n²) cost
        # of repeated ``str + str`` on a growing buffer for long responses.
        chunks: dict[str, list[str]] = {}
        last_id: str = ""
        for event in self.stream(message, thread_id=thread_id, **kwargs):
            if event.type == "messages-tuple" and event.data.get("type") == "ai":
                msg_id = event.data.get("id") or ""
                delta = event.data.get("content", "")
                if delta:
                    chunks.setdefault(msg_id, []).append(delta)
                    last_id = msg_id
        return "".join(chunks.get(last_id, ()))

    # ------------------------------------------------------------------
    # Public API — configuration queries
    # ------------------------------------------------------------------

    def list_models(self) -> dict:
        """列出配置中的模型及其思考、推理能力和令牌统计开关。"""
        token_usage_enabled = getattr(getattr(self._app_config, "token_usage", None), "enabled", False)
        if not isinstance(token_usage_enabled, bool):
            token_usage_enabled = False

        return {
            "models": [
                {
                    "name": model.name,
                    "model": getattr(model, "model", None),
                    "display_name": getattr(model, "display_name", None),
                    "description": getattr(model, "description", None),
                    "supports_thinking": getattr(model, "supports_thinking", False),
                    "supports_reasoning_effort": getattr(model, "supports_reasoning_effort", False),
                }
                for model in self._app_config.models
            ],
            "token_usage": {"enabled": token_usage_enabled},
        }

    def list_skills(self, enabled_only: bool = False) -> dict:
        """列出当前用户可见的技能；可选择仅返回已启用的技能。"""
        storage = get_or_new_user_skill_storage(get_effective_user_id(), app_config=self._app_config)
        return {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "license": s.license,
                    "category": s.category,
                    "enabled": s.enabled,
                }
                for s in storage.load_skills(enabled_only=enabled_only)
            ]
        }

    def get_memory(self) -> dict:
        """读取当前有效用户的完整持久化记忆数据。"""
        from deerflow.agents.memory import get_memory_manager

        return get_memory_manager().get_memory(user_id=get_effective_user_id())

    def export_memory(self) -> dict:
        """导出当前用户的记忆数据，供备份或迁移使用。"""
        from deerflow.agents.memory import get_memory_manager

        return get_memory_manager().get_memory(user_id=get_effective_user_id())

    def import_memory(self, memory_data: dict) -> dict:
        """导入并持久化完整记忆数据，返回存储后的结果。"""
        from deerflow.agents.memory import get_memory_manager

        return get_memory_manager().import_memory(memory_data, user_id=get_effective_user_id())

    def get_model(self, name: str) -> dict | None:
        """按名称查询模型配置；未找到时返回空值。"""
        model = self._app_config.get_model_config(name)
        if model is None:
            return None
        return {
            "name": model.name,
            "model": getattr(model, "model", None),
            "display_name": getattr(model, "display_name", None),
            "description": getattr(model, "description", None),
            "supports_thinking": getattr(model, "supports_thinking", False),
            "supports_reasoning_effort": getattr(model, "supports_reasoning_effort", False),
        }

    # ------------------------------------------------------------------
    # Public API — MCP configuration
    # ------------------------------------------------------------------

    def get_mcp_config(self) -> dict:
        """读取当前扩展配置中的 MCP 服务器定义。"""
        config = get_extensions_config()
        return {"mcp_servers": {name: server.model_dump() for name, server in config.mcp_servers.items()}}

    def update_mcp_config(self, mcp_servers: dict[str, dict]) -> dict:
        """写入 MCP 服务器配置、重载缓存并使已创建的智能体失效。"""
        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            raise FileNotFoundError("Cannot locate extensions_config.json. Set DEER_FLOW_EXTENSIONS_CONFIG_PATH or ensure it exists in the project root.")

        current_config = get_extensions_config()

        config_data = {
            "mcpServers": mcp_servers,
            "skills": {name: {"enabled": skill.enabled} for name, skill in current_config.skills.items()},
        }

        self._atomic_write_json(config_path, config_data)

        self._agent = None
        self._agent_config_key = None
        reloaded = reload_extensions_config()
        return {"mcp_servers": {name: server.model_dump() for name, server in reloaded.mcp_servers.items()}}

    # ------------------------------------------------------------------
    # Public API — skills management
    # ------------------------------------------------------------------

    def get_skill(self, name: str) -> dict | None:
        """按名称读取当前用户可见技能的元数据；不存在时返回空值。"""
        storage = get_or_new_user_skill_storage(get_effective_user_id(), app_config=self._app_config)
        skill = next((s for s in storage.load_skills(enabled_only=False) if s.name == name), None)
        if skill is None:
            return None
        return {
            "name": skill.name,
            "description": skill.description,
            "license": skill.license,
            "category": skill.category,
            "enabled": skill.enabled,
        }

    def update_skill(self, name: str, *, enabled: bool) -> dict:
        """更新指定技能的启用状态，刷新提示词缓存并重建智能体。"""
        storage = get_or_new_user_skill_storage(get_effective_user_id(), app_config=self._app_config)
        skills = storage.load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == name), None)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found")

        # PUBLIC skills → global extensions_config.json (shared state).
        # CUSTOM / LEGACY skills → per-user _skill_states.json (isolated state).
        from deerflow.skills.types import SkillCategory

        if skill.category == SkillCategory.PUBLIC:
            config_path = ExtensionsConfig.resolve_config_path()
            if config_path is None:
                raise FileNotFoundError("Cannot locate extensions_config.json. Set DEER_FLOW_EXTENSIONS_CONFIG_PATH or ensure it exists in the project root.")

            extensions_config = get_extensions_config()
            extensions_config.skills[name] = SkillStateConfig(enabled=enabled)

            config_data = {
                "mcpServers": {n: s.model_dump() for n, s in extensions_config.mcp_servers.items()},
                "skills": {n: {"enabled": sc.enabled} for n, sc in extensions_config.skills.items()},
            }

            self._atomic_write_json(config_path, config_data)
            reload_extensions_config()
        else:
            # CUSTOM / LEGACY: write per-user state
            from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

            if isinstance(storage, UserScopedSkillStorage):
                storage.set_skill_enabled_state(name, enabled)
            else:
                # Fallback for non-user-scoped storage (unlikely in practice)
                config_path = ExtensionsConfig.resolve_config_path()
                if config_path is None:
                    raise FileNotFoundError("Cannot locate extensions_config.json. Set DEER_FLOW_EXTENSIONS_CONFIG_PATH or ensure it exists in the project root.")
                extensions_config = get_extensions_config()
                extensions_config.skills[name] = SkillStateConfig(enabled=enabled)
                config_data = {
                    "mcpServers": {n: s.model_dump() for n, s in extensions_config.mcp_servers.items()},
                    "skills": {n: {"enabled": sc.enabled} for n, sc in extensions_config.skills.items()},
                }
                self._atomic_write_json(config_path, config_data)
                reload_extensions_config()

        # Invalidate the prompt cache for this caller (and for all users if
        # the changed skill is PUBLIC, since PUBLIC state is shared). Mirrors
        # what ``routers/configuration/skills.py::update_skill`` does — without this the
        # cached enabled-state would stay stale until process restart. See
        # review feedback on PR #3889.
        try:
            from deerflow.agents.lead_agent.prompt import clear_skills_system_prompt_cache, invalidate_user_skill_cache

            skill_category_value = skill.category.value if hasattr(skill.category, "value") else skill.category
            if skill_category_value == SkillCategory.PUBLIC.value:
                clear_skills_system_prompt_cache()
            else:
                invalidate_user_skill_cache(get_effective_user_id())
        except Exception as exc:
            # Don't let cache-invalidation failures mask the actual write
            # success — log and continue. The stale-cache window is bounded
            # by the next config reload.
            import logging

            logging.getLogger(__name__).warning("Failed to invalidate skills prompt cache after update_skill: %s", exc)

        self._agent = None
        self._agent_config_key = None

        updated = next((s for s in storage.load_skills(enabled_only=False) if s.name == name), None)
        if updated is None:
            raise RuntimeError(f"Skill '{name}' disappeared after update")
        return {
            "name": updated.name,
            "description": updated.description,
            "license": updated.license,
            "category": updated.category,
            "enabled": updated.enabled,
        }

    def install_skill(self, skill_path: str | Path) -> dict:
        """从本地技能归档安装技能，并返回安装结果或相应路径、格式错误。"""
        return get_or_new_user_skill_storage(get_effective_user_id(), app_config=self._app_config).install_skill_from_archive(skill_path)

    # ------------------------------------------------------------------
    # Public API — memory management
    # ------------------------------------------------------------------

    def reload_memory(self) -> dict:
        """从持久化介质重载当前用户记忆并使内存缓存失效。"""
        from deerflow.agents.memory import get_memory_manager

        manager = get_memory_manager()
        if hasattr(manager, "reload_memory"):
            return manager.reload_memory(user_id=get_effective_user_id())
        # Non-DeerMem backends have no reload concept; return current memory.
        return manager.get_memory(user_id=get_effective_user_id())

    def clear_memory(self) -> dict:
        """清除当前用户的全部持久化记忆。"""
        from deerflow.agents.memory import get_memory_manager

        return get_memory_manager().clear_memory(user_id=get_effective_user_id())

    def create_memory_fact(self, content: str, category: str = "context", confidence: float = 0.5) -> dict:
        """手动创建一条带类别和置信度的记忆事实。"""
        from deerflow.agents.memory import get_memory_manager

        manager = get_memory_manager()
        if not hasattr(manager, "create_fact"):
            raise NotImplementedError(f"create_fact not supported by memory backend '{type(manager).__name__}'")
        memory_data, fact_id = manager.create_fact(content=content, category=category, confidence=confidence, user_id=get_effective_user_id())
        if fact_id is None:
            raise ValueError("Fact was not stored because memory.max_facts kept higher-confidence facts")
        return memory_data

    def delete_memory_fact(self, fact_id: str) -> dict:
        """按事实标识删除当前用户的一条记忆。"""
        from deerflow.agents.memory import get_memory_manager

        manager = get_memory_manager()
        if not hasattr(manager, "delete_fact"):
            raise NotImplementedError(f"delete_fact not supported by memory backend '{type(manager).__name__}'")
        return manager.delete_fact(fact_id, user_id=get_effective_user_id())

    def update_memory_fact(
        self,
        fact_id: str,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
    ) -> dict:
        """更新一条记忆事实，仅修改显式提供的字段。"""
        from deerflow.agents.memory import get_memory_manager

        manager = get_memory_manager()
        if not hasattr(manager, "update_fact"):
            raise NotImplementedError(f"update_fact not supported by memory backend '{type(manager).__name__}'")
        return manager.update_fact(
            fact_id=fact_id,
            content=content,
            category=category,
            confidence=confidence,
            user_id=get_effective_user_id(),
        )

    def get_memory_config(self) -> dict:
        """返回记忆系统的启用状态、模式、注入和后端配置。"""
        from deerflow.config.memory_config import get_memory_config

        config = get_memory_config()
        return {
            "enabled": config.enabled,
            "mode": config.mode,
            "injection_enabled": config.injection_enabled,
            "shutdown_flush_timeout_seconds": config.shutdown_flush_timeout_seconds,
            "manager_class": config.manager_class,
            "backend_config": config.backend_config,
        }

    def get_memory_status(self) -> dict:
        """同时返回记忆系统配置与当前记忆数据。"""
        return {
            "config": self.get_memory_config(),
            "data": self.get_memory(),
        }

    # ------------------------------------------------------------------
    # Public API — file uploads
    # ------------------------------------------------------------------

    def upload_files(self, thread_id: str, files: list[str | Path]) -> dict:
        """将本地普通文件上传至线程隔离的上传目录。

        上传前统一验证所有路径，避免部分成功；重名文件自动改名。可转换的文档会尝试
        生成标记文本；若调用方正运行事件循环，则复用单工作线程完成转换桥接。
        """
        from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown

        # Validate all files upfront to avoid partial uploads.
        resolved_files = []
        seen_names: set[str] = set()
        has_convertible_file = False
        for f in files:
            p = Path(f)
            if not p.exists():
                raise FileNotFoundError(f"File not found: {f}")
            if not p.is_file():
                raise ValueError(f"Path is not a file: {f}")
            dest_name = claim_unique_filename(p.name, seen_names)
            resolved_files.append((p, dest_name))
            if not has_convertible_file and p.suffix.lower() in CONVERTIBLE_EXTENSIONS:
                has_convertible_file = True

        uploads_dir = ensure_uploads_dir(thread_id)
        uploaded_files: list[dict] = []

        conversion_pool = None
        if has_convertible_file:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                conversion_pool = None
            else:
                import concurrent.futures

                # Reuse one worker when already inside an event loop to avoid
                # creating a new ThreadPoolExecutor per converted file.
                conversion_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _convert_in_thread(path: Path):
            """在转换工作线程中运行异步文档转标记文本协程。"""
            return asyncio.run(convert_file_to_markdown(path))

        try:
            for src_path, dest_name in resolved_files:
                dest = uploads_dir / dest_name
                shutil.copy2(src_path, dest)

                info: dict[str, Any] = {
                    "filename": dest_name,
                    "size": dest.stat().st_size,
                    "path": str(dest),
                    "virtual_path": upload_virtual_path(dest_name),
                    "artifact_url": upload_artifact_url(thread_id, dest_name),
                }
                if dest_name != src_path.name:
                    info["original_filename"] = src_path.name

                if src_path.suffix.lower() in CONVERTIBLE_EXTENSIONS:
                    try:
                        if conversion_pool is not None:
                            md_path = conversion_pool.submit(_convert_in_thread, dest).result()
                        else:
                            md_path = asyncio.run(convert_file_to_markdown(dest))
                    except Exception:
                        logger.warning(
                            "Failed to convert %s to markdown",
                            src_path.name,
                            exc_info=True,
                        )
                        md_path = None

                    if md_path is not None:
                        info["markdown_file"] = md_path.name
                        info["markdown_path"] = str(uploads_dir / md_path.name)
                        info["markdown_virtual_path"] = upload_virtual_path(md_path.name)
                        info["markdown_artifact_url"] = upload_artifact_url(thread_id, md_path.name)

                uploaded_files.append(info)
        finally:
            if conversion_pool is not None:
                conversion_pool.shutdown(wait=True)

        return {
            "success": True,
            "files": uploaded_files,
            "message": f"Successfully uploaded {len(uploaded_files)} file(s)",
        }

    def list_uploads(self, thread_id: str) -> dict:
        """列出线程上传目录中的文件，并补充虚拟路径与产物访问地址。"""
        uploads_dir = get_uploads_dir(thread_id)
        result = list_files_in_dir(uploads_dir)
        return enrich_file_listing(result, thread_id)

    def delete_upload(self, thread_id: str, filename: str) -> dict:
        """删除线程上传文件及其关联转换产物，并拒绝路径穿越。"""
        from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS

        uploads_dir = get_uploads_dir(thread_id)
        return delete_file_safe(uploads_dir, filename, convertible_extensions=CONVERTIBLE_EXTENSIONS)

    # ------------------------------------------------------------------
    # Public API — artifacts
    # ------------------------------------------------------------------

    def get_artifact(self, thread_id: str, path: str) -> tuple[bytes, str]:
        """按线程与虚拟路径读取智能体产物，返回字节内容和推断的媒体类型。

        路径经用户与线程隔离规则解析；不存在、非文件或路径穿越都会报告对应错误。
        """
        try:
            actual = get_paths().resolve_virtual_path(thread_id, path, user_id=get_effective_user_id())
        except ValueError as exc:
            if "traversal" in str(exc):
                from deerflow.uploads.manager import PathTraversalError

                raise PathTraversalError("Path traversal detected") from exc
            raise
        if not actual.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        if not actual.is_file():
            raise ValueError(f"Path is not a file: {path}")

        mime_type, _ = mimetypes.guess_type(actual)
        return actual.read_bytes(), mime_type or "application/octet-stream"
