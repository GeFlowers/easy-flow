'''

Background agent execution.

Runs an agent graph inside an ``asyncio.Task``, publishing events to
a :class:`StreamBridge` as they are produced.

Uses ``graph.astream(stream_mode=[...])`` which gives correct full-state
snapshots for ``values`` mode, proper ``{node: writes}`` for ``updates``,
and ``(chunk, metadata)`` tuples for ``messages`` mode.

Note: ``events`` mode is not supported through the gateway — it requires
``graph.astream_events()`` which cannot simultaneously produce ``values``
snapshots.  The JS open-source LangGraph API server works around this via
internal checkpoint callbacks that are not exposed in the Python public API.
'''

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import os
import threading
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal, cast

from langgraph.checkpoint.base import empty_checkpoint

from deerflow.agents.goal_state import GoalEvaluation, GoalState
from deerflow.config.app_config import AppConfig
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.goal import (
    DEFAULT_MAX_GOAL_CONTINUATIONS,
    DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS,
    GoalWriteConflict,
    _call_checkpointer_method,
    _is_visible_message,
    _message_type,
    attach_goal_evaluation,
    compute_no_progress_count,
    create_goal_evaluator_model,
    evaluate_goal_completion,
    goal_thread_lock,
    latest_visible_assistant_signature,
    make_goal_continuation_message,
    read_thread_goal,
    should_continue_goal,
    visible_conversation_signature,
    write_thread_goal,
)
from deerflow.runtime.serialization import serialize
from deerflow.runtime.stream_bridge import StreamBridge
from deerflow.runtime.user_context import get_effective_user_id, resolve_runtime_user_id
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, get_current_trace_id, normalize_trace_id
from deerflow.tracing import inject_langfuse_metadata
from deerflow.utils.messages import message_to_text
from deerflow.workspace_changes import capture_workspace_snapshot, record_workspace_changes
from deerflow.workspace_changes.types import WorkspaceSnapshot

from .manager import RunManager, RunRecord
from .naming import resolve_root_run_name
from .schemas import RunStatus

logger = logging.getLogger(__name__)

_checkpoint_locks_guard = threading.Lock()
_checkpoint_locks_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = weakref.WeakKeyDictionary()


@asynccontextmanager
async def _checkpoint_thread_lock(thread_id: str) -> AsyncIterator[None]:
    '''

    序列化：checkpoint mutations for one thread without blocking goal commands.'''
    loop = asyncio.get_running_loop()
    with _checkpoint_locks_guard:
        locks = _checkpoint_locks_by_loop.get(loop)
        if locks is None:
            locks = {}
            _checkpoint_locks_by_loop[loop] = locks
        lock = locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[thread_id] = lock

    async with lock:
        yield


# LangGraph 的 graph.astream() 支持的 stream_mode 取值。
_VALID_LG_MODES = {"values", "updates", "checkpoints", "tasks", "debug", "messages", "custom"}


def _build_runtime_context(
    thread_id: str,
    run_id: str,
    caller_context: Any | None,
    app_config: AppConfig | None = None,
) -> dict[str, Any]:
    '''

    构建：the dict that becomes ``ToolRuntime.context`` for the run.

        Always includes ``thread_id`` and ``run_id``. Additional keys from the caller's
        ``config['context']`` (e.g. ``agent_name`` for the bootstrap flow — issue #2677)
        are merged in but never override ``thread_id``/``run_id``. The resolved
        ``AppConfig`` is added by the worker so tools can consume it without ambient
        global lookups.

        langgraph 1.1+ surfaces this as ``runtime.context`` via the parent runtime stored
        under ``config['configurable']['__pregel_runtime']`` — see
        ``langgraph.pregel.main`` where ``parent_runtime.merge(...)`` is invoked.
    '''
    runtime_ctx: dict[str, Any] = {"thread_id": thread_id, "run_id": run_id}
    if isinstance(caller_context, dict):
        for key, value in caller_context.items():
            if key == CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY:
                continue
            runtime_ctx.setdefault(key, value)
    if app_config is not None:
        runtime_ctx["app_config"] = app_config
    return runtime_ctx


@dataclass(frozen=True)
class RunContext:
    '''

    Infrastructure dependencies for a single agent run.

        Groups checkpointer, store, and persistence-related singletons so that
        ``run_agent`` (and any future callers) receive one object instead of a
        growing list of keyword arguments.
    '''

    checkpointer: Any
    store: Any | None = field(default=None)
    event_store: Any | None = field(default=None)
    run_events_config: Any | None = field(default=None)
    thread_store: Any | None = field(default=None)
    app_config: AppConfig | None = field(default=None)
    on_run_completed: Any | None = field(default=None)


def _install_runtime_context(config: dict, runtime_context: dict[str, Any]) -> None:
    '''把线程、运行、追踪和应用配置等受信任字段写入 LangGraph 上下文。'''
    existing_context = config.get("context")
    if isinstance(existing_context, dict):
        existing_context.setdefault("thread_id", runtime_context["thread_id"])
        existing_context.setdefault("run_id", runtime_context["run_id"])
        if DEERFLOW_TRACE_METADATA_KEY in runtime_context:
            existing_context.setdefault(DEERFLOW_TRACE_METADATA_KEY, runtime_context[DEERFLOW_TRACE_METADATA_KEY])
        if "app_config" in runtime_context:
            existing_context["app_config"] = runtime_context["app_config"]
        if CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY in runtime_context:
            existing_context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] = runtime_context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY]
        return

    config["context"] = dict(runtime_context)


def _compute_agent_factory_supports_app_config(agent_factory: Any) -> bool:
    '''检查 agent 工厂签名是否声明了 app_config 参数。'''
    try:
        return "app_config" in inspect.signature(agent_factory).parameters
    except (TypeError, ValueError):
        return False


@lru_cache(maxsize=128)
def _cached_agent_factory_supports_app_config(agent_factory: Any) -> bool:
    '''缓存工厂参数能力检查，避免每次运行都重新解析签名。'''
    return _compute_agent_factory_supports_app_config(agent_factory)


def _agent_factory_supports_app_config(agent_factory: Any) -> bool:
    '''读取缓存的工厂能力结果，并兼容不可哈希的可调用对象。'''
    try:
        return _cached_agent_factory_supports_app_config(agent_factory)
    except TypeError:
        # 某些可调用实例不可哈希，此时改用直接比较。
        return _compute_agent_factory_supports_app_config(agent_factory)


class _SubagentEventBuffer:
    '''

    Buffer subagent ``task_*`` step events and flush them in one locked batch (#3779).

        The live SSE bridge already forwards these events for real-time display; this
        additionally writes them so the subtask card's step history survives a reload.

        ``RunEventStore.put`` is documented as a low-frequency path — on Postgres each
        call opens its own transaction and takes a per-thread advisory lock. A deep
        subagent (``general-purpose`` runs up to ``max_turns=150``) emits hundreds of
        ``task_running`` steps on the hot stream loop, so persisting each with
        ``put()`` would serialize against the run's own message-batch writer. This
        accumulates recognized subagent events and writes them with ``put_batch``,
        which acquires the lock once per batch, honoring the store's contract.

        Best-effort: a missing store (run_events not configured) or an unrecognized
        chunk is a no-op, flush failures are logged but never propagate into the
        stream loop, and terminal ``subagent.end`` events flush eagerly so a completed
        subagent's step history is durable promptly rather than only at run end.
    '''

    #: 缓冲达到此事件数时执行刷新，限制单个深层子智能体造成的内存占用和刷新延迟，
    #: 同时避免每一步都获取锁。
    FLUSH_THRESHOLD = 25

    def __init__(self, event_store: Any | None, thread_id: str, run_id: str) -> None:
        '''初始化子任务事件缓冲区及其持久化作用域。'''
        self._event_store = event_store
        self._thread_id = thread_id
        self._run_id = run_id
        self._pending: list[dict[str, Any]] = []

    async def add(self, chunk: Any) -> None:
        '''

        缓存单个自定义流事件；达到阈值或遇到终止事件时批量写入。'''
        if self._event_store is None:
            return
        # 该包初始化会沿 executor → agents → tools → task_tool 的链路再次导入
        # deerflow.subagents，导致网关启动时发生循环导入。延迟到调用时导入可打断该循环。
        from deerflow.subagents.step_events import subagent_run_event

        record = subagent_run_event(chunk)
        if record is None:
            return
        self._pending.append({"thread_id": self._thread_id, "run_id": self._run_id, **record})
        if record["event_type"] == "subagent.end" or len(self._pending) >= self.FLUSH_THRESHOLD:
            await self.flush()

    async def flush(self) -> None:
        '''

        持久化：buffered events in one ``put_batch`` call; swallow store errors.'''
        if self._event_store is None or not self._pending:
            return
        batch = self._pending
        self._pending = []
        try:
            await self._event_store.put_batch(batch)
        except Exception:
            # 将失败批次放回队列前端，排在此后新入队的事件之前，避免临时存储故障
            # 悄悄丢弃子智能体步骤事件。
            self._pending = batch + self._pending
            logger.warning("Run %s: failed to persist %d subagent step event(s)", self._run_id, len(batch), exc_info=True)


async def run_agent(
    bridge: StreamBridge,
    run_manager: RunManager,
    record: RunRecord,
    *,
    ctx: RunContext,
    agent_factory: Any,
    graph_input: dict,
    config: dict,
    stream_modes: list[str] | None = None,
    stream_subgraphs: bool = False,
    interrupt_before: list[str] | Literal["*"] | None = None,
    interrupt_after: list[str] | Literal["*"] | None = None,
) -> None:
    '''在后台执行代理图，将运行事件写入消息桥，并负责检查点、持久化和终态收尾。'''

    # 从 RunContext 中提取基础设施依赖。
    checkpointer = ctx.checkpointer
    store = ctx.store
    event_store = ctx.event_store
    run_events_config = ctx.run_events_config
    thread_store = ctx.thread_store

    run_id = record.run_id
    thread_id = record.thread_id
    requested_modes: set[str] = set(stream_modes or ["values"])
    pre_run_checkpoint_id: str | None = None
    pre_run_snapshot: dict[str, Any] | None = None
    pre_run_workspace_snapshot: WorkspaceSnapshot | None = None
    workspace_changes_user_id: str | None = None
    snapshot_capture_failed = False
    llm_error_fallback_message: str | None = None
    # 本轮运行开始前已写入检查点的消息编号。流处理循环据此排除属于同一会话旧运行的
    # ``deerflow_error_fallback`` 标记，否则历史中的单个过期标记会让后续每轮运行都被标为 ``error``。
    pre_existing_message_ids: set[str] = set()

    journal = None
    # 缓存子智能体步骤事件并批量持久化（#3779）；开始流处理后赋值，并在 finally 中刷新。
    # 预先设为 None，确保流处理开始前发生异常时 finally 仍可安全执行。
    subagent_events: _SubagentEventBuffer | None = None

    if "events" in requested_modes:
        logger.info(
            "Run %s: 'events' stream_mode not supported in gateway (requires astream_events + checkpoint callbacks). Skipping.",
            run_id,
        )

    try:
        await run_manager.wait_for_prior_finalizing(thread_id, run_id)

        # 将这些操作放在 try 中，使任何异常（例如数据库写入事件失败）都经过
        # except/finally 分支，并向事件流桥接器发送 "end" 事件；否则流会一直等待终止事件。
        if event_store is not None:
            from deerflow.runtime.journal import RunJournal

            journal = RunJournal(
                run_id=run_id,
                thread_id=thread_id,
                event_store=event_store,
                track_token_usage=getattr(run_events_config, "track_token_usage", True),
                progress_reporter=lambda snapshot: run_manager.update_run_progress(run_id, **snapshot),
            )

        await run_manager.set_status(run_id, RunStatus.running)

        if event_store is not None:
            workspace_changes_user_id = get_effective_user_id()
            try:
                pre_run_workspace_snapshot = await capture_workspace_snapshot(
                    thread_id,
                    user_id=workspace_changes_user_id,
                )
            except Exception:
                logger.warning("Could not capture pre-run workspace snapshot for run %s", run_id, exc_info=True)

        # 保存运行前最新的检查点快照，以便回滚时恢复。
        if checkpointer is not None:
            try:
                config_for_check = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                ckpt_tuple = await checkpointer.aget_tuple(config_for_check)
                if ckpt_tuple is not None:
                    ckpt_config = getattr(ckpt_tuple, "config", {}).get("configurable", {})
                    pre_run_checkpoint_id = ckpt_config.get("checkpoint_id")
                    pre_run_snapshot = {
                        "checkpoint_ns": ckpt_config.get("checkpoint_ns", ""),
                        "checkpoint": copy.deepcopy(getattr(ckpt_tuple, "checkpoint", {})),
                        "metadata": copy.deepcopy(getattr(ckpt_tuple, "metadata", {})),
                        "pending_writes": copy.deepcopy(getattr(ckpt_tuple, "pending_writes", []) or []),
                    }
                    pre_existing_message_ids = _collect_pre_existing_message_ids(pre_run_snapshot)
            except Exception:
                snapshot_capture_failed = True
                logger.warning("Could not capture pre-run checkpoint snapshot for run %s", run_id, exc_info=True)

        await bridge.publish(
            run_id,
            "metadata",
            {
                "run_id": run_id,
                "thread_id": thread_id,
            },
        )

        # 3. 创建智能体。
        from langchain_core.runnables import RunnableConfig
        from langgraph.runtime import Runtime

        # 注入运行时上下文，使中间件和工具可通过 ToolRuntime.context 读取会话级数据。
        # langgraph-cli 会自动完成此操作；这里直接调用 ``agent.astream(config=...)`` 驱动图，
        # 没有传入官方 ``context=`` 参数，因此需要手动注入。
        runtime_ctx = _build_runtime_context(thread_id, run_id, config.get("context"), ctx.app_config)
        runtime_ctx[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] = frozenset(pre_existing_message_ids)
        incoming_metadata = config.get("metadata") if isinstance(config.get("metadata"), dict) else {}
        deerflow_trace_id = normalize_trace_id(incoming_metadata.get(DEERFLOW_TRACE_METADATA_KEY)) or get_current_trace_id()
        if deerflow_trace_id:
            runtime_ctx[DEERFLOW_TRACE_METADATA_KEY] = deerflow_trace_id
        # 使用哨兵键暴露本轮日志记录器，供中间件写入审计事件（例如记录被拦截的工具调用）。
        # 双下划线前缀表示这是运行时内部通道，用户代码不应依赖该键名。
        if journal is not None:
            runtime_ctx["__run_journal"] = journal
        _install_runtime_context(config, runtime_ctx)
        runtime = Runtime(context=cast(Any, runtime_ctx), store=store)
        config.setdefault("configurable", {})["__pregel_runtime"] = runtime

        # 将 RunJournal 注入为 LangChain 回调处理器：on_llm_end 记录令牌用量，
        # on_chain_start/end 记录调用生命周期。
        if journal is not None:
            config.setdefault("callbacks", []).append(journal)

        # 注入 Langfuse 跟踪属性，使 langchain 回调处理器能把会话编号、用户编号、跟踪名称和标签
        # 附加到根跟踪。与 ``DeerFlowClient.stream`` 共用此辅助函数，避免两个入口行为不一致；
        # 辅助函数使用 setdefault，因此调用方提供的元数据优先。
        inject_langfuse_metadata(
            config,
            thread_id=thread_id,
            user_id=resolve_runtime_user_id(runtime),
            assistant_id=record.assistant_id,
            model_name=record.model_name,
            environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
            deerflow_trace_id=deerflow_trace_id,
        )

        # 解析时机放在运行时上下文安装之后，确保上下文和 configurable 反映本轮实际执行的智能体名称。
        config.setdefault("run_name", resolve_root_run_name(config, record.assistant_id))
        initial_runnable_config = RunnableConfig(**config)

        def _continuation_runnable_config() -> RunnableConfig:
            '''构造指向根检查点命名空间的新配置，用于目标自动续跑。'''
            continuation_config = dict(config)
            configurable = dict(continuation_config.get("configurable", {}) or {})
            configurable["checkpoint_ns"] = ""
            configurable.pop("checkpoint_id", None)
            configurable.pop("checkpoint_map", None)
            continuation_config["configurable"] = configurable
            return RunnableConfig(**continuation_config)

        if ctx.app_config is not None and _agent_factory_supports_app_config(agent_factory):
            agent = agent_factory(config=initial_runnable_config, app_config=ctx.app_config)
        else:
            agent = agent_factory(config=initial_runnable_config)

        # 从智能体元数据读取最终解析出的模型名称。agent.py 中的 _resolve_model_name 在请求名称
        # 不在允许列表时可能回退到默认模型；此处同步更新，确保持久化的 model_name 与实际模型一致。
        if record.model_name is not None:
            resolved = getattr(agent, "metadata", {}) or {}
            if isinstance(resolved, dict):
                effective = resolved.get("model_name")
                if effective and effective != record.model_name:
                    await run_manager.update_model_name(record.run_id, effective)

        # 4. 挂接检查点保存器和存储。
        if checkpointer is not None:
            agent.checkpointer = checkpointer
        if store is not None:
            agent.store = store

        if interrupt_before:
            agent.interrupt_before_nodes = interrupt_before
        if interrupt_after:
            agent.interrupt_after_nodes = interrupt_after

        #    "events" 不是有效的 astream 模式，因此跳过。
        #    "messages-tuple" 对应 LangGraph 的 "messages" 模式。
        lg_modes: list[str] = []
        for m in requested_modes:
            if m == "messages-tuple":
                lg_modes.append("messages")
            elif m == "events":
                continue
            elif m in _VALID_LG_MODES:
                lg_modes.append(m)
        if not lg_modes:
            lg_modes = ["values"]

        seen: set[str] = set()
        deduped: list[str] = []
        for m in lg_modes:
            if m not in seen:
                seen.add(m)
                deduped.append(m)
        lg_modes = deduped

        logger.info("Run %s: streaming with modes %s (requested: %s)", run_id, lg_modes, requested_modes)

        # 缓存子智能体步骤事件并批量持久化（#3779），避免流循环每一步都单独调用 put()。
        # 在 finally 中刷新，确保中止或异常路径中的缓存步骤也会保存。
        subagent_events = _SubagentEventBuffer(event_store, thread_id, run_id)

        goal_evaluator_model: Any | None = None

        def _get_goal_evaluator_model() -> Any:
            '''惰性创建并复用本次运行的目标评估模型。'''
            nonlocal goal_evaluator_model
            if goal_evaluator_model is None:
                goal_evaluator_model = create_goal_evaluator_model(
                    model_name=record.model_name,
                    app_config=ctx.app_config,
                )
            return goal_evaluator_model

        async def _stream_once(input_payload: Any, stream_config: RunnableConfig) -> None:
            '''执行一轮 agent 流式调用，转发 SSE 并收集目标及子任务事件。'''
            nonlocal llm_error_fallback_message
            async with _checkpoint_thread_lock(thread_id):
                if len(lg_modes) == 1 and not stream_subgraphs:
                    single_mode = lg_modes[0]
                    async for chunk in agent.astream(input_payload, config=stream_config, stream_mode=single_mode):
                        if record.abort_event.is_set():
                            logger.info("Run %s abort requested — stopping", run_id)
                            break
                        llm_error_fallback_message = llm_error_fallback_message or _extract_llm_error_fallback_message(chunk, pre_existing_message_ids)
                        sse_event = _lg_mode_to_sse_event(single_mode)
                        await bridge.publish(run_id, sse_event, serialize(chunk, mode=single_mode))
                        if single_mode == "custom":
                            await subagent_events.add(chunk)
                    return
                async for item in agent.astream(
                    input_payload,
                    config=stream_config,
                    stream_mode=lg_modes,
                    subgraphs=stream_subgraphs,
                ):
                    if record.abort_event.is_set():
                        logger.info("Run %s abort requested — stopping", run_id)
                        break

                    mode, chunk = _unpack_stream_item(item, lg_modes, stream_subgraphs)
                    if mode is None:
                        continue

                    llm_error_fallback_message = llm_error_fallback_message or _extract_llm_error_fallback_message(chunk, pre_existing_message_ids)
                    sse_event = _lg_mode_to_sse_event(mode)
                    await bridge.publish(run_id, sse_event, serialize(chunk, mode=mode))
                    if mode == "custom":
                        await subagent_events.add(chunk)

        # 7. 处理用户请求的轮次，并按需继续执行不可见的目标轮次。
        # 仅在第一个（用户可见）轮次前清除过期 stop_reason。
        # 后续轮次保留用户轮次的限制原因：即使隐藏的目标评估轮次
        if isinstance(runtime.context, dict):
            runtime.context.pop("stop_reason", None)
        await _stream_once(graph_input, initial_runnable_config)
        while not record.abort_event.is_set() and not llm_error_fallback_message and (journal is None or not journal.had_llm_error_fallback):
            continuation_input = await _prepare_goal_continuation_input(
                bridge=bridge,
                checkpointer=checkpointer,
                thread_id=thread_id,
                run_id=run_id,
                model_name=record.model_name,
                app_config=ctx.app_config,
                evaluator_model_factory=_get_goal_evaluator_model,
                abort_event=record.abort_event,
                user_id=resolve_runtime_user_id(runtime),
                deerflow_trace_id=deerflow_trace_id,
            )
            if continuation_input is None or record.abort_event.is_set():
                break
            await _stream_once(continuation_input, _continuation_runnable_config())

        if record.abort_event.is_set():
            await run_manager.set_finalizing(run_id, True)
            action = record.abort_action
            if action == "rollback":
                await run_manager.set_status(run_id, RunStatus.error, error="Rolled back by user")
                try:
                    await _rollback_to_pre_run_checkpoint(
                        checkpointer=checkpointer,
                        thread_id=thread_id,
                        run_id=run_id,
                        pre_run_checkpoint_id=pre_run_checkpoint_id,
                        pre_run_snapshot=pre_run_snapshot,
                        snapshot_capture_failed=snapshot_capture_failed,
                    )
                    logger.info("Run %s rolled back to pre-run checkpoint %s", run_id, pre_run_checkpoint_id)
                except Exception:
                    logger.warning("Failed to rollback checkpoint for run %s", run_id, exc_info=True)
            else:
                await run_manager.set_status(run_id, RunStatus.interrupted)
        elif llm_error_fallback_message or (journal is not None and journal.had_llm_error_fallback):
            error_msg = llm_error_fallback_message
            if error_msg is None and journal is not None:
                error_msg = journal.llm_error_fallback_message
            error_msg = error_msg or "LLM provider failed after retries"
            await run_manager.set_status(run_id, RunStatus.error, error=error_msg)
        else:
            runtime_context = runtime.context if isinstance(runtime.context, dict) else None
            # 强制终止运行的防护中间件会移除 tool_calls，并将 stop_reason 写入 runtime.context，
            # 以便工作器把终止原因记录到运行记录中：
            # 如果将来有更多防护机制扩展 stop_reason 的含义，可改为发布/收集模式：
            # 每个防护中间件把限制原因写入独立的 runtime.context 通道，再由工作器统一收集，
            # 而不是让所有防护都直接写入同一个键。
            stop_reason = runtime_context.get("stop_reason") if runtime_context is not None else None
            await run_manager.set_status(run_id, RunStatus.success, stop_reason=stop_reason)

    except asyncio.CancelledError:
        await run_manager.set_finalizing(run_id, True)
        action = record.abort_action
        if action == "rollback":
            await run_manager.set_status(run_id, RunStatus.error, error="Rolled back by user")
            try:
                await _rollback_to_pre_run_checkpoint(
                    checkpointer=checkpointer,
                    thread_id=thread_id,
                    run_id=run_id,
                    pre_run_checkpoint_id=pre_run_checkpoint_id,
                    pre_run_snapshot=pre_run_snapshot,
                    snapshot_capture_failed=snapshot_capture_failed,
                )
                logger.info("Run %s was cancelled and rolled back", run_id)
            except Exception:
                logger.warning("Run %s cancellation rollback failed", run_id, exc_info=True)
        else:
            await run_manager.set_status(run_id, RunStatus.interrupted)
            logger.info("Run %s was cancelled", run_id)

    except Exception as exc:
        error_msg = f"{exc}"
        logger.exception("Run %s failed: %s", run_id, error_msg)
        await run_manager.set_status(run_id, RunStatus.error, error=error_msg)
        await bridge.publish(
            run_id,
            "error",
            {
                "message": error_msg,
                "name": type(exc).__name__,
            },
        )

    finally:
        # 保存仍在缓存中的子智能体步骤事件（#3779），包括流循环尚未自行刷新就中止或异常的路径。
        if subagent_events is not None:
            await subagent_events.flush()

        if event_store is not None and pre_run_workspace_snapshot is not None:
            try:
                await record_workspace_changes(
                    event_store,
                    thread_id,
                    run_id,
                    pre_run_workspace_snapshot,
                    user_id=workspace_changes_user_id,
                )
            except Exception:
                logger.warning("Failed to record workspace changes for run %s", run_id, exc_info=True)

        # 刷新日志事件缓存，并持久化运行完成信息。
        if journal is not None:
            try:
                await journal.flush()
            except Exception:
                logger.warning("Failed to flush journal for run %s", run_id, exc_info=True)

            try:
                completion = journal.get_completion_data()
                await run_manager.update_run_completion(run_id, status=record.status.value, **completion)
            except Exception:
                logger.warning("Failed to persist run completion for %s (non-fatal)", run_id, exc_info=True)

        if checkpointer is not None and record.status == RunStatus.interrupted:
            try:
                await run_manager.wait_for_prior_finalizing(thread_id, run_id)
                if not await run_manager.has_later_started_run(thread_id, run_id):
                    await _ensure_interrupted_title(checkpointer=checkpointer, thread_id=thread_id, app_config=ctx.app_config, graph_input=graph_input)
            except Exception:
                logger.debug("Failed to generate interrupted title for thread %s (non-fatal)", thread_id)

        # 将检查点中的标题同步到 threads_meta.display_name。
        if checkpointer is not None and thread_store is not None:
            try:
                ckpt_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                ckpt_tuple = await checkpointer.aget_tuple(ckpt_config)
                if ckpt_tuple is not None:
                    ckpt = getattr(ckpt_tuple, "checkpoint", {}) or {}
                    title = ckpt.get("channel_values", {}).get("title")
                    if title:
                        await thread_store.update_display_name(thread_id, title)
            except Exception:
                logger.debug("Failed to sync title for thread %s (non-fatal)", thread_id)

        # 将运行时长写入检查点元数据，读取历史记录时就不必再关联运行记录和事件。
        if checkpointer is not None and record.status == RunStatus.success:
            try:
                created = datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
                updated = datetime.fromisoformat(record.updated_at.replace("Z", "+00:00"))
                # 保持旧历史记录语义：turn_duration 是 RunRecord 的完整生命周期秒数，包含排队等待时间。
                # 成功轮次不足一秒时保存为零。
                duration = max(0, int((updated - created).total_seconds()))
                await _persist_run_duration(
                    checkpointer=checkpointer,
                    thread_id=thread_id,
                    run_id=run_id,
                    duration_seconds=duration,
                )
            except Exception:
                logger.debug("Failed to persist run duration for thread %s run %s (non-fatal)", thread_id, run_id)

        if thread_store is not None:
            try:
                final_status = "idle" if record.status == RunStatus.success else record.status.value
                await thread_store.update_status(thread_id, final_status)
            except Exception:
                logger.debug("Failed to update thread_meta status for %s (non-fatal)", thread_id)

        if ctx.on_run_completed is not None:
            try:
                await ctx.on_run_completed(record)
            except Exception:
                logger.warning("Run completion hook failed for %s (non-fatal)", run_id, exc_info=True)
        if record.finalizing:
            await run_manager.set_finalizing(run_id, False)

        await bridge.publish_end(run_id)
        asyncio.create_task(bridge.cleanup(run_id, delay=60))




def _checkpoint_id(checkpoint_tuple: Any) -> str | None:
    '''从检查点元组配置或正文中提取检查点 ID。'''
    config = getattr(checkpoint_tuple, "config", {}) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    checkpoint_id = configurable.get("checkpoint_id") if isinstance(configurable, dict) else None
    if isinstance(checkpoint_id, str):
        return checkpoint_id
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    if isinstance(checkpoint, dict) and isinstance(checkpoint.get("id"), str):
        return checkpoint["id"]
    return None


def _goal_instance_matches(left: GoalState | None, right: GoalState | None) -> bool:
    '''确认两个目标仍代表同一条活动目标，防止并发写入覆盖新目标。'''
    if not left or not right:
        return False
    same_status = left.get("status") == right.get("status") == "active"
    same_objective = left.get("objective") == right.get("objective")
    same_created_at = left.get("created_at") == right.get("created_at")
    return same_status and same_objective and same_created_at


def _read_checkpoint_messages(checkpoint_tuple: Any) -> list[Any]:
    '''从检查点的 messages 频道读取消息列表，其他格式返回空列表。'''
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    messages = channel_values.get("messages", []) if isinstance(channel_values, dict) else []
    return messages if isinstance(messages, list) else []


def _read_checkpoint_goal(checkpoint_tuple: Any) -> GoalState | None:
    '''从检查点读取目标状态副本，避免调用方意外修改原快照。'''
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    raw_goal = channel_values.get("goal") if isinstance(channel_values, dict) else None
    return copy.deepcopy(raw_goal) if isinstance(raw_goal, dict) else None


def _has_durable_goal_turn_receipt(checkpoint_tuple: Any, messages: list[Any]) -> bool:
    '''确认检查点已提交且最后一条可见消息是助手回复，作为完成回执。'''
    if _checkpoint_id(checkpoint_tuple) is None:
        return False
    if getattr(checkpoint_tuple, "pending_writes", None):
        return False
    visible_messages = []
    for message in messages:
        if _is_visible_message(message) and message_to_text(message).strip():
            visible_messages.append(message)
    if not visible_messages:
        return False
    return _message_type(visible_messages[-1]) == "ai"


def _stand_down_reason(goal: GoalState, evaluation: GoalEvaluation, no_progress_count: int) -> str | None:
    '''根据阻塞类型、续跑上限和无进展次数决定是否停止自动续跑。'''
    if evaluation["satisfied"]:
        return None
    if evaluation["blocker"] != "goal_not_met_yet":
        return f"blocked:{evaluation['blocker']}"
    # 默认限制与 should_continue_goal 保持一致，确保两个门控函数对缺少这些字段的目标字典采用相同处理。
    if int(goal.get("continuation_count", 0)) >= int(goal.get("max_continuations", DEFAULT_MAX_GOAL_CONTINUATIONS)):
        return "max_continuations_reached"
    if no_progress_count >= int(goal.get("max_no_progress_continuations", DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS)):
        return "no_progress_detected"
    return None


async def _persist_goal_evaluation(
    *,
    bridge: StreamBridge,
    checkpointer: Any,
    thread_id: str,
    run_id: str,
    goal: GoalState,
    evaluation: GoalEvaluation,
    no_progress_count: int,
    continuation_count: int | None = None,
    stand_down_reason: str | None = None,
    evidence_signature: str = "",
) -> GoalState | None:
    '''校验目标与检查点版本后保存评估结果，并向订阅端广播最新状态。'''
    try:
        async with goal_thread_lock(thread_id):
            checkpoint_tuple = await _call_checkpointer_method(
                checkpointer,
                "aget_tuple",
                "get_tuple",
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
            )
            if checkpoint_tuple is None:
                return None
            current_goal = _read_checkpoint_goal(checkpoint_tuple)
            if current_goal is None or not _goal_instance_matches(goal, current_goal):
                return None
            # 为避免并发竞态，在锁内根据最新 current_goal 重新计算 continuation_count。
            # 调用方使用的目标快照可能已过期，另一个并发续接可能已经增加了计数。
            if continuation_count is not None:
                current_count = int(current_goal.get("continuation_count", 0))
                continuation_count = max(continuation_count, current_count + 1)
            expected_checkpoint_id = _checkpoint_id(checkpoint_tuple)
            updated_goal = attach_goal_evaluation(
                current_goal,
                evaluation,
                run_id=run_id,
                continuation_count=continuation_count,
                no_progress_count=no_progress_count,
                stand_down_reason=stand_down_reason,
                evidence_signature=evidence_signature,
            )
            values = await write_thread_goal(
                checkpointer,
                thread_id,
                updated_goal,
                as_node="goal_evaluator",
                expected_checkpoint_id=expected_checkpoint_id,
            )
        await bridge.publish(run_id, "values", serialize(values, mode="values"))
        return updated_goal
    except GoalWriteConflict:
        return None
    except Exception:
        logger.warning("Could not persist goal evaluation for thread %s", thread_id, exc_info=True)
        return None


async def _reread_goal_and_checkpoint(checkpointer: Any, thread_id: str) -> tuple[GoalState | None, Any]:
    '''

    重新读取目标和最新检查点，判断并发期间状态是否已发生变化。'''
    goal = await read_thread_goal(checkpointer, thread_id)
    checkpoint_tuple = await _call_checkpointer_method(
        checkpointer,
        "aget_tuple",
        "get_tuple",
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
    )
    return goal, checkpoint_tuple


async def _prepare_goal_continuation_input(
    *,
    bridge: StreamBridge,
    checkpointer: Any,
    thread_id: str,
    run_id: str,
    model_name: str | None,
    app_config: AppConfig | None,
    evaluator_model_factory: Any | None = None,
    abort_event: asyncio.Event | None = None,
    user_id: str | None = None,
    deerflow_trace_id: str | None = None,
) -> dict[str, Any] | None:
    '''

    评估活动目标，并在目标仍可继续时构造隐藏的续跑输入。

        NOTE: The re-reads below catch a racing user message or ``/goal clear``
        before we queue a continuation. Goal writes then serialize per thread and
        pass the checkpoint id they read from, so stale evaluator writes stand down
        instead of clobbering a newer goal change.
    '''
    if checkpointer is None:
        return None
    if abort_event is not None and abort_event.is_set():
        return None

    try:
        goal = await read_thread_goal(checkpointer, thread_id)
    except Exception:
        logger.warning("Could not read goal for thread %s after run %s", thread_id, run_id, exc_info=True)
        return None
    if not goal or goal.get("status") != "active":
        return None

    async def _persist(
        goal: GoalState,
        evaluation: GoalEvaluation,
        no_progress_count: int,
        *,
        stand_down_reason: str | None = None,
        continuation_count: int | None = None,
    ) -> GoalState | None:
        '''

        记录：the evaluation against the still-current goal instance.'''
        return await _persist_goal_evaluation(
            bridge=bridge,
            checkpointer=checkpointer,
            thread_id=thread_id,
            run_id=run_id,
            goal=goal,
            evaluation=evaluation,
            no_progress_count=no_progress_count,
            continuation_count=continuation_count,
            stand_down_reason=stand_down_reason,
            evidence_signature=evidence_signature,
        )

    try:
        checkpoint_tuple = await _call_checkpointer_method(
            checkpointer,
            "aget_tuple",
            "get_tuple",
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        )
        if checkpoint_tuple is None:
            return None
        checkpoint_id_before = _checkpoint_id(checkpoint_tuple)
        messages = _read_checkpoint_messages(checkpoint_tuple)
        conversation_signature_before = visible_conversation_signature(messages)
        evidence_signature = latest_visible_assistant_signature(messages)

        if not _has_durable_goal_turn_receipt(checkpoint_tuple, messages):
            evaluation = GoalEvaluation(
                satisfied=False,
                blocker="run_failed",
                reason="No durable assistant end-of-turn receipt was available.",
                evidence_summary="",
            )
            no_progress_count = compute_no_progress_count(goal, evaluation, evidence_signature=evidence_signature)
            await _persist(goal, evaluation, no_progress_count, stand_down_reason="no_durable_end_of_turn")
            return None

        if abort_event is not None and abort_event.is_set():
            return None
        evaluator_model = evaluator_model_factory() if evaluator_model_factory is not None else None
        evaluation = await evaluate_goal_completion(
            goal,
            messages,
            model=evaluator_model,
            model_name=model_name,
            app_config=app_config,
            thread_id=thread_id,
            user_id=user_id,
            deerflow_trace_id=deerflow_trace_id,
        )
        if abort_event is not None and abort_event.is_set():
            return None
    except Exception:
        logger.warning("Goal evaluator failed for thread %s after run %s", thread_id, run_id, exc_info=True)
        return None

    no_progress_count = compute_no_progress_count(goal, evaluation, evidence_signature=evidence_signature)

    # 重新检查目标和用户可见对话在评估期间是否变化；若评估期间有用户消息或 /goal 清除操作并发到达，应以用户操作为准。
    try:
        current_goal, current_checkpoint_tuple = await _reread_goal_and_checkpoint(checkpointer, thread_id)
    except Exception:
        logger.warning("Could not re-check goal state for thread %s after evaluation", thread_id, exc_info=True)
        return None

    if not _goal_instance_matches(goal, current_goal) or current_checkpoint_tuple is None:
        return None

    checkpoint_changed = _checkpoint_id(current_checkpoint_tuple) != checkpoint_id_before
    messages_changed = visible_conversation_signature(_read_checkpoint_messages(current_checkpoint_tuple)) != conversation_signature_before
    if checkpoint_changed or messages_changed:
        await _persist(current_goal, evaluation, no_progress_count, stand_down_reason="thread_changed_after_evaluation")
        return None

    if evaluation["satisfied"]:
        try:
            async with goal_thread_lock(thread_id):
                latest_checkpoint_tuple = await _call_checkpointer_method(
                    checkpointer,
                    "aget_tuple",
                    "get_tuple",
                    {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
                )
                if latest_checkpoint_tuple is None:
                    return None
                latest_goal = _read_checkpoint_goal(latest_checkpoint_tuple)
                if latest_goal is None or not _goal_instance_matches(goal, latest_goal):
                    return None
                values = await write_thread_goal(
                    checkpointer,
                    thread_id,
                    None,
                    as_node="goal_evaluator",
                    expected_checkpoint_id=_checkpoint_id(latest_checkpoint_tuple),
                )
            await bridge.publish(run_id, "values", serialize(values, mode="values"))
        except GoalWriteConflict:
            return None
        except Exception:
            logger.warning("Could not clear satisfied goal for thread %s", thread_id, exc_info=True)
        return None

    stand_down_reason = _stand_down_reason(goal, evaluation, no_progress_count)
    if stand_down_reason is not None or not should_continue_goal(goal, evaluation, no_progress_count=no_progress_count):
        await _persist(goal, evaluation, no_progress_count, stand_down_reason=stand_down_reason)
        return None

    next_count = int(goal.get("continuation_count", 0)) + 1
    updated_goal = await _persist(goal, evaluation, no_progress_count, continuation_count=next_count)
    if updated_goal is None:
        return None

    # 最后一道检查：上方的持久化操作已更新检查点编号，因此这里只能通过用户可见对话的签名判断是否并发出现了新用户轮次。
    try:
        latest_goal, latest_checkpoint_tuple = await _reread_goal_and_checkpoint(checkpointer, thread_id)
    except Exception:
        logger.warning("Could not verify queued goal continuation for thread %s", thread_id, exc_info=True)
        return None
    if not _goal_instance_matches(updated_goal, latest_goal) or latest_checkpoint_tuple is None:
        return None
    if visible_conversation_signature(_read_checkpoint_messages(latest_checkpoint_tuple)) != conversation_signature_before:
        # 此处不要再传 continuation_count：上方的持久化已将其提交为 next_count。
        # 再传 next_count 会让 _persist_goal_evaluation 的竞态保护（#4088）把同一次写入
        # 误认为 current_count 再次增加，从而将这次被暂停而非实际执行的续接重复计入预算。
        # 省略该参数即可保留已提交的计数，与本函数其他暂停路径保持一致。
        await _persist(
            latest_goal,
            evaluation,
            no_progress_count,
            stand_down_reason="thread_changed_before_continuation",
        )
        return None

    logger.info(
        "Run %s continuing thread %s for active goal (%d/%d)",
        run_id,
        thread_id,
        updated_goal.get("continuation_count", next_count),
        updated_goal.get("max_continuations", 0),
    )
    return {"messages": [make_goal_continuation_message(updated_goal, evaluation)]}


async def _rollback_to_pre_run_checkpoint(
    *,
    checkpointer: Any,
    thread_id: str,
    run_id: str,
    pre_run_checkpoint_id: str | None,
    pre_run_snapshot: dict[str, Any] | None,
    snapshot_capture_failed: bool,
) -> None:
    '''

    将线程状态恢复到运行开始前保存的检查点快照。'''
    if checkpointer is None:
        logger.info("Run %s rollback requested but no checkpointer is configured", run_id)
        return

    if snapshot_capture_failed:
        logger.warning("Run %s rollback skipped: pre-run checkpoint snapshot capture failed", run_id)
        return

    if pre_run_snapshot is None:
        await _call_checkpointer_method(checkpointer, "adelete_thread", "delete_thread", thread_id)
        logger.info("Run %s rollback reset thread %s to empty state", run_id, thread_id)
        return

    checkpoint_to_restore = None
    metadata_to_restore: dict[str, Any] = {}
    checkpoint_ns = ""
    checkpoint = pre_run_snapshot.get("checkpoint")
    if not isinstance(checkpoint, dict):
        logger.warning("Run %s rollback skipped: invalid pre-run checkpoint snapshot", run_id)
        return
    checkpoint_to_restore = checkpoint
    if checkpoint_to_restore.get("id") is None and pre_run_checkpoint_id is not None:
        checkpoint_to_restore = {**checkpoint_to_restore, "id": pre_run_checkpoint_id}
    if checkpoint_to_restore.get("id") is None:
        logger.warning("Run %s rollback skipped: pre-run checkpoint has no checkpoint id", run_id)
        return
    restore_marker = _new_checkpoint_marker()
    checkpoint_to_restore = {
        **checkpoint_to_restore,
        "id": restore_marker["id"],
        "ts": restore_marker["ts"],
    }
    metadata = pre_run_snapshot.get("metadata", {})
    metadata_to_restore = metadata if isinstance(metadata, dict) else {}
    raw_checkpoint_ns = pre_run_snapshot.get("checkpoint_ns")
    checkpoint_ns = raw_checkpoint_ns if isinstance(raw_checkpoint_ns, str) else ""

    channel_versions = checkpoint_to_restore.get("channel_versions")
    new_versions = dict(channel_versions) if isinstance(channel_versions, dict) else {}

    restore_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}}
    restored_config = await _call_checkpointer_method(
        checkpointer,
        "aput",
        "put",
        restore_config,
        checkpoint_to_restore,
        metadata_to_restore if isinstance(metadata_to_restore, dict) else {},
        new_versions,
    )
    if not isinstance(restored_config, dict):
        raise RuntimeError(f"Run {run_id} rollback restore returned invalid config: expected dict")
    restored_configurable = restored_config.get("configurable", {})
    if not isinstance(restored_configurable, dict):
        raise RuntimeError(f"Run {run_id} rollback restore returned invalid config payload")
    restored_checkpoint_id = restored_configurable.get("checkpoint_id")
    if not restored_checkpoint_id:
        raise RuntimeError(f"Run {run_id} rollback restore did not return checkpoint_id")

    pending_writes = pre_run_snapshot.get("pending_writes", [])
    if not pending_writes:
        return

    writes_by_task: dict[str, list[tuple[str, Any]]] = {}
    for item in pending_writes:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise RuntimeError(f"Run {run_id} rollback failed: pending_write is not a 3-tuple: {item!r}")
        task_id, channel, value = item
        if not isinstance(channel, str):
            raise RuntimeError(f"Run {run_id} rollback failed: pending_write has non-string channel: task_id={task_id!r}, channel={channel!r}")
        writes_by_task.setdefault(str(task_id), []).append((channel, value))

    for task_id, writes in writes_by_task.items():
        await _call_checkpointer_method(
            checkpointer,
            "aput_writes",
            "put_writes",
            restored_config,
            writes,
            task_id=task_id,
        )


def _new_checkpoint_marker() -> dict[str, str]:
    '''创建空检查点并提取重置消息频道所需的 ID 和时间戳。'''
    marker = empty_checkpoint()
    return {"id": marker["id"], "ts": marker["ts"]}


def _bump_channel_version(checkpointer: Any, current_version: Any) -> Any:
    '''

    返回：a strictly-different next version for a checkpoint channel.

        The PostgreSQL-backed LangGraph saver
        persist channel blobs keyed by ``channel_versions[<channel>]``, so the
        new value MUST differ from the prior value. We delegate to the
        checkpointer's ``get_next_version`` when available — that is the canonical
        versioning scheme each saver picks (int, monotonic float, or
        UUID-shaped string). When the checkpointer doesn't expose it (or it
        returns ``None``/an unchanged value), fall back to a defensive bump that
        still guarantees inequality.
    '''
    get_next_version = getattr(checkpointer, "get_next_version", None)
    if callable(get_next_version):
        try:
            next_version = get_next_version(current_version, None)
        except Exception:
            next_version = None
        if next_version is not None and next_version != current_version:
            return next_version

    if isinstance(current_version, bool):
        # ``bool`` 是 ``int`` 的子类；将 True/False 当作 1/0 处理，避免直接对布尔值执行加法而让读者困惑。
        return int(current_version) + 1
    if isinstance(current_version, int):
        return current_version + 1
    if isinstance(current_version, float):
        # 与 LangGraph 默认的浮点版本号策略一致，版本号单调递增。
        return current_version + 1.0
    if isinstance(current_version, str):
        try:
            return str(int(current_version) + 1)
        except ValueError:
            return f"{current_version}.1"
    return 1


def _checkpoint_identity(ckpt_tuple: Any | None, checkpoint: dict[str, Any]) -> str | None:
    '''从检查点元组配置优先读取 ID，缺失时回退到检查点正文。'''
    tuple_config = getattr(ckpt_tuple, "config", {}) or {}
    tuple_configurable = tuple_config.get("configurable", {}) if isinstance(tuple_config, dict) else {}
    if isinstance(tuple_configurable, dict):
        checkpoint_id = tuple_configurable.get("checkpoint_id")
        if isinstance(checkpoint_id, str) and checkpoint_id:
            return checkpoint_id
    checkpoint_id = checkpoint.get("id")
    return checkpoint_id if isinstance(checkpoint_id, str) and checkpoint_id else None


def _checkpoint_namespace(ckpt_tuple: Any | None) -> str:
    '''读取检查点元组的命名空间，供写入时定位相同子图状态。'''
    tuple_config = getattr(ckpt_tuple, "config", {}) or {}
    tuple_configurable = tuple_config.get("configurable", {}) if isinstance(tuple_config, dict) else {}
    checkpoint_ns = tuple_configurable.get("checkpoint_ns", "") if isinstance(tuple_configurable, dict) else ""
    return checkpoint_ns if isinstance(checkpoint_ns, str) else ""


def _graph_input_messages(graph_input: Any | None) -> list[Any]:
    '''兼容字典输入中的列表或元组消息并统一返回列表。'''
    if not isinstance(graph_input, dict):
        return []
    messages = graph_input.get("messages")
    if isinstance(messages, list):
        return messages
    if isinstance(messages, tuple):
        return list(messages)
    return []


def _title_generation_state(channel_values: dict[str, Any], graph_input: Any | None) -> dict[str, Any]:
    '''构造标题生成所需状态；检查点消息为空时使用本轮图输入补齐。'''
    state = dict(channel_values)
    messages = state.get("messages")
    if not messages:
        fallback_messages = _graph_input_messages(graph_input)
        if fallback_messages:
            state["messages"] = fallback_messages
    return state


def valid_duration_entry(run_id: Any, duration_seconds: Any) -> bool:
    '''

    检查：that (run_id, duration_seconds) is a well-formed duration entry.'''
    return isinstance(run_id, str) and bool(run_id) and isinstance(duration_seconds, int) and not isinstance(duration_seconds, bool)


async def persist_run_durations(
    *,
    checkpointer: Any,
    thread_id: str,
    durations: dict[str, int],
) -> bool:
    '''

    将已校验的运行耗时合并进元数据检查点，不重写消息频道。

        Durations accumulate so the history fast path can serve every known turn
        from the latest checkpoint.  Per-entry overhead is negligible (~50 bytes
        per run_id) compared to the messages channel blob written on every graph
        checkpoint, so no pruning is needed.
    '''
    updates = {run_id: max(0, duration_seconds) for run_id, duration_seconds in durations.items() if valid_duration_entry(run_id, duration_seconds)}
    if not updates:
        return False

    ckpt_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    async with _checkpoint_thread_lock(thread_id):
        for _attempt in range(3):
            ckpt_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", ckpt_config)
            if ckpt_tuple is None:
                return False

            checkpoint = dict(getattr(ckpt_tuple, "checkpoint", {}) or {})
            metadata = dict(getattr(ckpt_tuple, "metadata", {}) or {})
            raw_run_durations = metadata.get("run_durations")
            run_durations = {key: value for key, value in raw_run_durations.items() if valid_duration_entry(key, value)} if isinstance(raw_run_durations, dict) else {}
            changed_durations = {run_id: duration for run_id, duration in updates.items() if run_durations.get(run_id) != duration}
            if not changed_durations:
                return False

            run_durations.update(changed_durations)
            parent_checkpoint_id = _checkpoint_identity(ckpt_tuple, checkpoint)
            latest_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", ckpt_config)
            latest_checkpoint = dict(getattr(latest_tuple, "checkpoint", {}) or {}) if latest_tuple is not None else {}
            if _checkpoint_identity(latest_tuple, latest_checkpoint) != parent_checkpoint_id:
                continue

            checkpoint.update(_new_checkpoint_marker())
            metadata["source"] = "update"
            prev_step = metadata.get("step")
            metadata["step"] = (prev_step + 1) if isinstance(prev_step, int) else 1
            metadata["run_durations"] = run_durations
            metadata["writes"] = {"runtime_run_duration": {"run_ids": sorted(changed_durations)}}

            checkpoint_ns = _checkpoint_namespace(ckpt_tuple)
            write_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_checkpoint_id,
                }
            }
            await _call_checkpointer_method(
                checkpointer,
                "aput",
                "put",
                write_config,
                checkpoint,
                metadata,
                {},
            )
            return True
    return False


async def _persist_run_duration(
    *,
    checkpointer: Any,
    thread_id: str,
    run_id: str,
    duration_seconds: int,
) -> None:
    '''

    持久化：one completed run duration in the thread checkpoint metadata.'''
    await persist_run_durations(
        checkpointer=checkpointer,
        thread_id=thread_id,
        durations={run_id: duration_seconds},
    )


async def _ensure_interrupted_title(*, checkpointer: Any, thread_id: str, app_config: AppConfig | None, graph_input: Any | None = None) -> str | None:
    '''

    持久化：a local fallback title for interrupted first-turn runs.

        Returns the title that is now persisted (existing or newly written), or
        ``None`` when no checkpoint is available or no title text can be derived.
        Idempotent: re-invoking against a checkpoint that already carries a title
        short-circuits without writing a new checkpoint.
    '''
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    middleware = TitleMiddleware(app_config=app_config) if app_config is not None else TitleMiddleware()
    ckpt_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    for _attempt in range(3):
        ckpt_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", ckpt_config)
        checkpoint = copy.deepcopy(getattr(ckpt_tuple, "checkpoint", {}) or {}) if ckpt_tuple is not None else empty_checkpoint()
        channel_values = dict(checkpoint.get("channel_values", {}) or {})
        existing_title = channel_values.get("title")
        if existing_title:
            return existing_title

        result = middleware._generate_title_result(_title_generation_state(channel_values, graph_input), allow_partial_exchange=True)
        title = result.get("title") if isinstance(result, dict) else None
        if not title:
            return None

        # ``empty_checkpoint()`` 每次都会生成新编号；只有真实元组的标识足够稳定，可用于比较快照是否过期。
        base_identity = _checkpoint_identity(ckpt_tuple, checkpoint) if ckpt_tuple is not None else None
        latest_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", ckpt_config)
        latest_checkpoint = copy.deepcopy(getattr(latest_tuple, "checkpoint", {}) or {}) if latest_tuple is not None else empty_checkpoint()
        latest_identity = _checkpoint_identity(latest_tuple, latest_checkpoint) if latest_tuple is not None else None
        if base_identity is None:
            if latest_identity is not None:
                continue
        elif latest_identity != base_identity:
            continue

        checkpoint = latest_checkpoint
        channel_values = dict(checkpoint.get("channel_values", {}) or {})
        existing_title = channel_values.get("title")
        if existing_title:
            return existing_title

        channel_values["title"] = title
        marker = _new_checkpoint_marker()
        checkpoint.update({"id": marker["id"], "ts": marker["ts"], "channel_values": channel_values})

        # 增加 ``channel_versions["title"]`` 并在 ``new_versions`` 中声明变更，确保 PostgreSQL 保存器
        # 实际写入新数据块。保存器会从 ``put`` 中移除内联 ``channel_values``，只保存
        # ``new_versions`` 列出的通道；此处与同文件中的 ``_rollback_to_pre_run_checkpoint`` 保持一致。
        channel_versions = dict(checkpoint.get("channel_versions", {}) or {})
        next_title_version = _bump_channel_version(checkpointer, channel_versions.get("title"))
        channel_versions["title"] = next_title_version
        checkpoint["channel_versions"] = channel_versions

        metadata = dict(getattr(latest_tuple, "metadata", {}) or {})
        metadata["source"] = "update"
        prev_step = metadata.get("step")
        metadata["step"] = (prev_step + 1) if isinstance(prev_step, int) else 1
        metadata["writes"] = {"runtime_interrupt_title": {"title": title}}

        checkpoint_ns = _checkpoint_namespace(latest_tuple)
        write_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}}
        await _call_checkpointer_method(
            checkpointer,
            "aput",
            "put",
            write_config,
            checkpoint,
            metadata,
            {"title": next_title_version},
        )
        return title

    return None


def _lg_mode_to_sse_event(mode: str) -> str:
    '''

    映射：LangGraph internal stream_mode name to SSE event name.

        LangGraph's ``astream(stream_mode="messages")`` produces message
        tuples.  The SSE protocol calls this ``messages-tuple`` when the
        client explicitly requests it, but the default SSE event name used
        by LangGraph Platform is simply ``"messages"``.
    '''
    return mode


def _error_fallback_message_from_metadata(metadata: dict[str, Any], content: Any) -> str:
    '''按错误详情、原因、消息正文的优先级生成可见的模型故障说明。'''
    detail = metadata.get("error_detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    reason = metadata.get("error_reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    if isinstance(content, str) and content.strip():
        return content.strip()[:2000]
    return "LLM provider failed after retries"


def _message_id(obj: Any) -> str | None:
    '''

    从消息对象或字典中提取非空字符串消息 ID。'''
    msg_id = getattr(obj, "id", None)
    if isinstance(msg_id, str) and msg_id:
        return msg_id
    if isinstance(obj, dict):
        raw = obj.get("id")
        if isinstance(raw, str) and raw:
            return raw
    return None


def _try_extract_from_message(obj: Any, pre_existing_ids: set[str] | None = None) -> str | None:
    '''

    检查单条消息是否携带本轮模型错误回退标记。

        Messages whose id appears in ``pre_existing_ids`` are skipped — those are
        history checkpointed by a *prior* run on this thread and any fallback
        marker on them was already accounted for when that earlier run finished.
        Without this filter, a single past run that ended with a fallback marker
        would mark every subsequent run on the same thread as ``error``, because
        LangGraph replays the full message history through ``stream_mode="values"``.
    '''
    if pre_existing_ids:
        msg_id = _message_id(obj)
        if msg_id is not None and msg_id in pre_existing_ids:
            return None

    additional_kwargs = getattr(obj, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and additional_kwargs.get("deerflow_error_fallback"):
        return _error_fallback_message_from_metadata(additional_kwargs, getattr(obj, "content", None))

    if isinstance(obj, dict):
        nested_kwargs = obj.get("additional_kwargs")
        if isinstance(nested_kwargs, dict) and nested_kwargs.get("deerflow_error_fallback"):
            return _error_fallback_message_from_metadata(nested_kwargs, obj.get("content"))
    return None


def _extract_llm_error_fallback_message(value: Any, pre_existing_ids: set[str] | None = None) -> str | None:
    '''

    查找：LLM fallback markers in streamed LangGraph chunks.

        Error fallback messages returned by model-call middleware are not guaranteed
        to pass through LLM end callbacks, but they do appear in graph state chunks.

        Messages whose id appears in ``pre_existing_ids`` are ignored — they are
        history from prior runs on the same thread (LangGraph replays the full
        messages channel in ``stream_mode="values"`` chunks), and any error
        fallback in that history was already resolved when its run finished.
    '''
    # 快速路径：stream_mode="values" 产生的大型状态块在顶层包含 "messages" 列表。
    # 只扫描该列表，避免递归遍历庞大的状态字典。
    if isinstance(value, dict):
        messages = value.get("messages")
        if isinstance(messages, (list, tuple)):
            for msg in messages:
                result = _try_extract_from_message(msg, pre_existing_ids)
                if result is not None:
                    return result
            # 回退标记附加在 messages 通道中的 AI 消息上，不会出现在 values 状态块的其他位置。
            return None
        # 没有顶层 "messages" 时，通常这是以节点名称为键的小型 "updates" 状态块；
        # 继续执行深度遍历，这类数据的遍历成本较低。

    # 对 updates、messages、tuple 和 list 模式执行深度遍历。这些数据块较小，完整递归的开销可以接受。
    seen: set[int] = set()

    def walk(obj: Any) -> str | None:
        '''递归检查消息容器并避开循环引用，寻找本轮错误回退标记。'''
        oid = id(obj)
        if oid in seen:
            return None
        seen.add(oid)

        result = _try_extract_from_message(obj, pre_existing_ids)
        if result is not None:
            return result

        if isinstance(obj, dict):
            for item in obj.values():
                result = walk(item)
                if result is not None:
                    return result
            return None

        if isinstance(obj, (list, tuple, set)):
            for item in obj:
                result = walk(item)
                if result is not None:
                    return result
        return None

    return walk(value)


def _collect_pre_existing_message_ids(snapshot: dict[str, Any] | None) -> set[str]:
    '''

    从运行前检查点提取历史消息 ID，供本轮过滤旧错误标记。

        Used by :func:`run_agent` to mask stale ``deerflow_error_fallback`` markers
        on history messages so they don't trip the current run's failure path. A
        missing or malformed snapshot yields an empty set (best-effort — we
        intentionally never raise from this helper).
    '''
    if not isinstance(snapshot, dict):
        return set()
    checkpoint = snapshot.get("checkpoint")
    if not isinstance(checkpoint, dict):
        return set()
    channel_values = checkpoint.get("channel_values")
    if not isinstance(channel_values, dict):
        return set()
    messages = channel_values.get("messages")
    if not isinstance(messages, (list, tuple)):
        return set()
    ids: set[str] = set()
    for msg in messages:
        msg_id = _message_id(msg)
        if msg_id is not None:
            ids.add(msg_id)
    return ids


def _unpack_stream_item(
    item: Any,
    lg_modes: list[str],
    stream_subgraphs: bool,
) -> tuple[str | None, Any]:
    '''

    将多模式或子图流项目拆成事件模式、命名空间和数据块。

        Returns ``(None, None)`` if the item cannot be parsed.
    '''
    if stream_subgraphs:
        if isinstance(item, tuple) and len(item) == 3:
            _ns, mode, chunk = item
            return str(mode), chunk
        if isinstance(item, tuple) and len(item) == 2:
            mode, chunk = item
            return str(mode), chunk
        return None, None

    if isinstance(item, tuple) and len(item) == 2:
        mode, chunk = item
        return str(mode), chunk

    # 回退处理：取第一个模式产生的单元素输出。
    return lg_modes[0] if lg_modes else None, item
