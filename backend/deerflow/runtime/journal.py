'''

通过 LangChain 回调捕获运行事件。

RunJournal 连接 LangChain 回调机制与可插拔的 RunEventStore，
将回调数据规范化为 RunEvent 记录，并累计令牌用量。

主要设计约定：
- 不实现 on_llm_new_token，仅通过 on_llm_end 接收完整消息。
- on_chat_model_start 接收完整的结构化提示消息，并提取本轮用户输入用于运行摘要；
  此时消息结构完整，比在每个节点触发的 on_chain_start 更可靠。
- parent_run_id=None 时，on_chain_start 发出 run.start 追踪事件，标记根调用。
- on_llm_end 以 message.model_dump() 格式保存完整模型回复。
- 令牌用量在内存中累计，运行完成时写入运行记录。
- 通过注入标签识别调用方（lead_agent／subagent:{name}／middleware:{name}）。
'''

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.human_input import read_human_input_response
from deerflow.utils.messages import message_to_text, restore_original_human_message

if TYPE_CHECKING:
    from deerflow.runtime.events.store.base import RunEventStore

logger = logging.getLogger(__name__)

_LEGACY_SUMMARY_MESSAGE_NAME = "summary"
_RECONCILED_TOOL_MESSAGE_NAMES = frozenset({"ask_clarification"})
_PERSISTED_HIDDEN_HUMAN_INPUT_RESPONSE_SOURCES = frozenset({"ask_clarification"})


def _should_persist_human_input_message(message: BaseMessage) -> bool:
    '''仅保存真实用户输入及需要在对话记录中回放的人工输入回复。'''
    if not isinstance(message, HumanMessage):
        return False
    if message.name == _LEGACY_SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui") is not True:
        return True
    response = read_human_input_response(message.additional_kwargs)
    return response is not None and response["source"] in _PERSISTED_HIDDEN_HUMAN_INPUT_RESPONSE_SOURCES


class RunJournal(BaseCallbackHandler):
    '''

    将 LangChain 回调事件写入 RunEventStore 的处理器。'''

    def __init__(
        self,
        run_id: str,
        thread_id: str,
        event_store: RunEventStore,
        *,
        track_token_usage: bool = True,
        flush_threshold: int = 20,
        progress_reporter: Callable[[dict], Awaitable[None]] | None = None,
        progress_flush_interval: float = 5.0,
    ):
        '''初始化运行事件记录器、批量写缓冲区和令牌统计状态。'''
        super().__init__()
        self.run_id = run_id
        self.thread_id = thread_id
        self._store = event_store
        self._track_tokens = track_token_usage
        self._flush_threshold = flush_threshold
        self._progress_reporter = progress_reporter
        self._progress_flush_interval = progress_flush_interval

        self._buffer: list[dict] = []
        self._pending_flush_tasks: set[asyncio.Task[None]] = set()
        self._pending_progress_task: asyncio.Task[None] | None = None
        self._pending_progress_delayed = False
        self._progress_dirty = False
        self._last_progress_flush = 0.0

        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_tokens = 0
        self._llm_call_count = 0

        self._lead_agent_tokens = 0
        self._subagent_tokens = 0
        self._middleware_tokens = 0

        self._tokens_by_model: dict[str, dict[str, int]] = {}

        self._counted_llm_run_ids: set[str] = set()
        self._counted_external_source_ids: set[str] = set()
        self._counted_message_llm_run_ids: set[str] = set()
        self._memory_context_recorded = False

        self._last_ai_msg: str | None = None
        self._first_human_msg: str | None = None
        self._msg_count = 0
        self._had_llm_error_fallback = False
        self._llm_error_fallback_message: str | None = None

        self._llm_start_times: dict[str, float] = {}

        self._llm_call_index = 0
        self._seen_llm_starts: set[str] = set()
        self._current_run_tool_call_names: dict[str, str] = {}
        self._persisted_tool_message_identities: set[str] = set()


    @staticmethod
    def _message_text(message: BaseMessage) -> str:
        '''

        从消息的混合内容结构中提取可展示文本。'''
        return message_to_text(message, text_attribute_fallback=True)

    def _record_message_summary(self, message: BaseMessage, *, caller: str | None = None) -> None:
        '''

        更新持久化运行记录所需的消息数量及最近助手回复摘要。'''
        self._msg_count += 1

        is_ai_message = isinstance(message, AIMessage) or getattr(message, "type", None) == "ai"
        if is_ai_message and (caller is None or caller == "lead_agent"):
            text = self._message_text(message).strip()
            if text:
                self._last_ai_msg = text[:2000]

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        '''仅为根图调用记录运行开始事件，忽略内部子链启动。'''
        caller = self._identify_caller(tags)
        if parent_run_id is None:
            chain_name = (serialized or {}).get("name", "unknown")
            self._put(
                event_type="run.start",
                category="trace",
                content={"chain": chain_name},
                metadata={"caller": caller, **(metadata or {})},
            )

    def on_chain_end(
        self,
        outputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        '''在根图结束时补齐遗漏的工具消息、记录输出并刷新事件缓冲。'''
        if parent_run_id is not None:
            return
        self._reconcile_final_tool_messages(outputs)
        self._put(event_type="run.end", category="outputs", content=outputs, metadata={"status": "success"})
        self._flush_sync()

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        '''记录根链执行错误并尝试立即刷新运行事件。'''
        self._put(
            event_type="run.error",
            category="error",
            content=str(error),
            metadata={"error_type": type(error).__name__},
        )
        self._flush_sync()


    def on_chat_model_start(
        self,
        serialized: dict,
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        '''

        在模型调用开始时读取结构化消息，并保存本轮用户输入。

                此处是提取本轮用户消息的统一入口：消息结构完整，
                回调仅在真实模型调用时触发，且消息未因检查点裁剪而压缩。
        '''
        rid = str(run_id)
        self._llm_start_times[rid] = time.monotonic()
        self._llm_call_index += 1
        self._seen_llm_starts.add(rid)

        logger.debug(
            "on_chat_model_start %s: tags=%s num_batches=%d message_counts=%s",
            run_id,
            tags,
            len(messages),
            [len(batch) for batch in messages],
        )

        caller = self._identify_caller(tags)
        if caller == "lead_agent" and not self._first_human_msg and messages:
            for batch in reversed(messages):
                for m in reversed(batch):
                    if _should_persist_human_input_message(m):
                        persisted_message = restore_original_human_message(m)
                        self.set_first_human_message(self._message_text(persisted_message))
                        self._put(
                            event_type="llm.human.input",
                            category="message",
                            content=persisted_message.model_dump(),
                            metadata={"caller": caller},
                        )
                        self._record_message_summary(persisted_message, caller=caller)
                        break
                if self._first_human_msg:
                    break

    def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id: UUID, parent_run_id: UUID | None = None, tags: list[str] | None = None, metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        '''在旧式语言模型回调路径中记录调用起始时间以计算延迟。'''
        self._llm_start_times[str(run_id)] = time.monotonic()

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        '''持久化完整模型响应，并累计令牌、延迟、模型及调用方统计。'''
        messages: list[AnyMessage] = []
        logger.debug("on_llm_end %s: tags=%s", run_id, tags)
        for generation in response.generations:
            for gen in generation:
                if hasattr(gen, "message"):
                    messages.append(gen.message)
                else:
                    logger.warning(f"on_llm_end {run_id}: generation has no message attribute: {gen}")

        for message in messages:
            caller = self._identify_caller(tags)
            self._remember_current_run_tool_calls(message, caller=caller)

            rid = str(run_id)
            start = self._llm_start_times.pop(rid, None)
            latency_ms = int((time.monotonic() - start) * 1000) if start else None

            usage = getattr(message, "usage_metadata", None)
            usage_dict = dict(usage) if usage else {}
            additional_kwargs = getattr(message, "additional_kwargs", None) or {}
            if isinstance(additional_kwargs, dict) and additional_kwargs.get("deerflow_error_fallback"):
                self._had_llm_error_fallback = True
                detail = additional_kwargs.get("error_detail")
                reason = additional_kwargs.get("error_reason")
                fallback_text = self._message_text(message).strip()
                if isinstance(detail, str) and detail.strip():
                    self._llm_error_fallback_message = detail.strip()
                elif isinstance(reason, str) and reason.strip():
                    self._llm_error_fallback_message = reason.strip()
                elif fallback_text:
                    self._llm_error_fallback_message = fallback_text[:2000]

            call_index = self._llm_call_index
            if rid not in self._seen_llm_starts:
                self._llm_call_index += 1
                call_index = self._llm_call_index
                self._seen_llm_starts.add(rid)

            self._put(
                event_type="llm.ai.response",
                category="message",
                content=message.model_dump(),
                metadata={
                    "caller": caller,
                    "usage": usage_dict,
                    "latency_ms": latency_ms,
                    "llm_call_index": call_index,
                },
            )
            if rid not in self._counted_message_llm_run_ids:
                self._record_message_summary(message, caller=caller)

            if self._track_tokens:
                input_tk = usage_dict.get("input_tokens", 0) or 0
                output_tk = usage_dict.get("output_tokens", 0) or 0
                total_tk = usage_dict.get("total_tokens", 0) or 0
                if total_tk == 0:
                    total_tk = input_tk + output_tk
                if total_tk > 0 and rid not in self._counted_llm_run_ids:
                    self._counted_llm_run_ids.add(rid)
                    self._total_input_tokens += input_tk
                    self._total_output_tokens += output_tk
                    self._total_tokens += total_tk
                    self._llm_call_count += 1

                    if caller.startswith("subagent:"):
                        self._subagent_tokens += total_tk
                    elif caller.startswith("middleware:"):
                        self._middleware_tokens += total_tk
                    else:
                        self._lead_agent_tokens += total_tk

                    response_metadata = getattr(message, "response_metadata", None) or {}
                    per_call_model: str | None = None
                    if isinstance(response_metadata, Mapping):
                        per_call_model = response_metadata.get("model_name") or response_metadata.get("model")
                    self._record_model_usage(per_call_model, input_tk, output_tk, total_tk, self._extract_cache_read(usage_dict))

                    self._schedule_progress_flush()

        if messages:
            self._counted_message_llm_run_ids.add(str(run_id))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        '''清理失败调用的计时状态并记录模型错误事件。'''
        self._llm_start_times.pop(str(run_id), None)
        self._put(event_type="llm.error", category="trace", content=str(error))

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, inputs=None, **kwargs):
        '''

        记录工具启动及其调用标识，供日志关联。'''
        tool_call_id = str(run_id)
        logger.debug("Tool start for node %s, tool_call_id=%s, tags=%s", run_id, tool_call_id, tags)

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        '''

        在工具结束时保存结果消息，并记录结束日志。'''
        try:
            if isinstance(output, ToolMessage):
                msg = cast(ToolMessage, output)
                self._persist_tool_result_message(msg)
            elif isinstance(output, Command):
                cmd = cast(Command, output)
                messages = cmd.update.get("messages", [])
                for message in messages:
                    if isinstance(message, BaseMessage):
                        self._persist_tool_result_message(message)
                    else:
                        logger.warning(f"on_tool_end {run_id}: command update message is not BaseMessage: {type(message)}")
            else:
                logger.warning(f"on_tool_end {run_id}: output is not ToolMessage: {type(output)}")
        finally:
            logger.debug("Tool end for node %s", run_id)


    @staticmethod
    def _message_identity(message: BaseMessage) -> str | None:
        '''优先用工具调用 ID、其次用消息 ID 构造消息去重键。'''
        tool_call_id = getattr(message, "tool_call_id", None)
        if isinstance(tool_call_id, str) and tool_call_id:
            return f"tool:{tool_call_id}"
        message_id = getattr(message, "id", None)
        if isinstance(message_id, str) and message_id:
            return f"message:{message_id}"
        return None

    @staticmethod
    def _tool_call_value(tool_call: Any, key: str) -> Any:
        '''兼容字典或对象形式的工具调用，读取指定属性。'''
        if isinstance(tool_call, Mapping):
            return tool_call.get(key)
        return getattr(tool_call, key, None)

    def _remember_current_run_tool_calls(self, message: AnyMessage, *, caller: str) -> None:
        '''记录主智能体本轮发出的工具调用名称，用于结束时补齐特定回复。'''
        if caller != "lead_agent":
            return
        is_ai_message = isinstance(message, AIMessage) or getattr(message, "type", None) == "ai"
        if not is_ai_message:
            return
        tool_calls = getattr(message, "tool_calls", None) or []
        if not isinstance(tool_calls, list):
            return
        for tool_call in tool_calls:
            tool_call_id = self._tool_call_value(tool_call, "id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                continue
            name = self._tool_call_value(tool_call, "name")
            self._current_run_tool_call_names[tool_call_id] = str(name or "")

    def _persist_tool_result_message(self, message: BaseMessage) -> None:
        '''写入工具结果消息并更新去重标识及运行消息摘要。'''
        self._put(event_type="llm.tool.result", category="message", content=message.model_dump())
        identity = self._message_identity(message)
        if identity:
            self._persisted_tool_message_identities.add(identity)
        self._record_message_summary(message)

    def _final_output_messages(self, outputs: Any) -> list[Any]:
        '''从根图输出字典中提取最终 messages 列表。'''
        if isinstance(outputs, Mapping):
            messages = outputs.get("messages", [])
            return messages if isinstance(messages, list) else []
        return []

    def _should_reconcile_tool_message(self, message: ToolMessage) -> bool:
        '''判断最终状态中的工具消息是否属于尚未记录的人工输入工具结果。'''
        if message.additional_kwargs.get("hide_from_ui") is True:
            return False
        tool_call_id = getattr(message, "tool_call_id", None)
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return False
        tool_call_name = self._current_run_tool_call_names.get(tool_call_id)
        if tool_call_name is None:
            return False
        message_name = getattr(message, "name", None)
        if message_name not in _RECONCILED_TOOL_MESSAGE_NAMES and tool_call_name not in _RECONCILED_TOOL_MESSAGE_NAMES:
            return False
        identity = self._message_identity(message)
        return identity is not None and identity not in self._persisted_tool_message_identities

    def _reconcile_final_tool_messages(self, outputs: Any) -> None:
        '''扫描最终图状态，并补存回调链未捕获的工具结果消息。'''
        for message in self._final_output_messages(outputs):
            if not isinstance(message, ToolMessage):
                continue
            if self._should_reconcile_tool_message(message):
                self._persist_tool_result_message(message)

    def _put(self, *, event_type: str, category: str, content: str | dict = "", metadata: dict | None = None) -> None:
        '''把标准化事件加入批次缓冲，达到阈值时触发异步刷新。'''
        self._buffer.append(
            {
                "thread_id": self.thread_id,
                "run_id": self.run_id,
                "event_type": event_type,
                "category": category,
                "content": content,
                "metadata": metadata or {},
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._buffer) >= self._flush_threshold:
            self._flush_sync()

    def _flush_sync(self) -> None:
        '''

        在回调线程中调度批量异步写入；没有事件循环时保留缓冲等待显式刷新。

                BaseCallbackHandler 的方法是同步的。存在运行中的事件循环时，
                调度异步 ``put_batch``；否则事件留在缓冲区，稍后由工作器
                ``finally`` 块中的异步 ``flush()`` 调用刷新。
        '''
        if not self._buffer:
            return
        # 同一个运行同时只能有一批事件写入，避免后台任务间并发提交。
        if self._pending_flush_tasks:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        batch = self._buffer.copy()
        self._buffer.clear()
        task = loop.create_task(self._flush_async(batch))
        self._pending_flush_tasks.add(task)
        task.add_done_callback(self._on_flush_done)

    async def _flush_async(self, batch: list[dict]) -> None:
        '''批量写入事件仓储，失败时将整批事件放回缓冲供后续重试。'''
        try:
            await self._store.put_batch(batch)
        except Exception:
            logger.warning(
                "Failed to flush %d events for run %s — returning to buffer",
                len(batch),
                self.run_id,
                exc_info=True,
            )
            self._buffer = batch + self._buffer

    def _on_flush_done(self, task: asyncio.Task) -> None:
        '''回收已完成的刷新任务并记录未处理异常。'''
        self._pending_flush_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("Journal flush task failed: %s", exc)

    def _identify_caller(self, tags: list[str] | None) -> str:
        '''从回调标签识别主智能体、子智能体或中间件调用来源。'''
        _tags = tags or []
        for tag in _tags:
            if isinstance(tag, str) and (tag.startswith("subagent:") or tag.startswith("middleware:") or tag == "lead_agent"):
                return tag
        return "lead_agent"

    def _record_model_usage(
        self,
        model_name: str | None,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cache_read_tokens: int = 0,
    ) -> None:
        '''

        按模型累计单次调用的令牌用量，并仅在有缓存命中时写入该统计项。

                缺失或为空的 ``model_name`` 统一归入 ``"unknown"`` 分组，
                确保供应方未提供 ``response_metadata.model_name`` 时仍可统计用量。

                ``cache_read_tokens`` 表示提示词缓存命中量，来源于
                ``usage_metadata.input_token_details.cache_read``。仅在其非零时
                写入分组字段，使不提供缓存统计的供应方保持原有数据结构。
        '''
        if total_tokens <= 0:
            return
        bucket = self._tokens_by_model.setdefault(
            model_name or "unknown",
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        bucket["input_tokens"] += int(input_tokens or 0)
        bucket["output_tokens"] += int(output_tokens or 0)
        bucket["total_tokens"] += int(total_tokens)
        if cache_read_tokens > 0:
            bucket["cache_read_tokens"] = bucket.get("cache_read_tokens", 0) + int(cache_read_tokens)

    @staticmethod
    def _extract_cache_read(usage_dict: dict) -> int:
        '''

        从 LangChain 用量结构提取提示词缓存命中的输入令牌数。'''
        details = usage_dict.get("input_token_details") or {}
        if not isinstance(details, Mapping):
            return 0
        try:
            return max(int(details.get("cache_read") or 0), 0)
        except (TypeError, ValueError):
            return 0


    def record_external_llm_usage_records(
        self,
        records: list[dict[str, int | str | None]],
    ) -> None:
        '''

        记录来自外部来源（例如子智能体）的令牌用量。

                每条记录应包含：
                    source_run_id: 防止重复计数的唯一标识。
                    caller: 调用方标签（如 "subagent:general-purpose"）。
                    model_name: 单次调用的实际模型名称（str 或 None；缺失时
                        归入 ``"unknown"`` 分组）。
                    input_tokens: 输入令牌数。
                    output_tokens: 输出令牌数。
                    total_tokens: 总令牌数（为零或缺失时由输入量加输出量计算）。
                    cache_read_tokens: 可选的提示词缓存命中输入令牌数。
        '''
        if not self._track_tokens:
            return
        for record in records:
            source_id = str(record.get("source_run_id", ""))
            if not source_id:
                continue
            if source_id in self._counted_external_source_ids:
                continue

            total_tk = record.get("total_tokens", 0) or 0
            if total_tk <= 0:
                input_tk = record.get("input_tokens", 0) or 0
                output_tk = record.get("output_tokens", 0) or 0
                total_tk = input_tk + output_tk
            if total_tk <= 0:
                continue

            input_tk = record.get("input_tokens", 0) or 0
            output_tk = record.get("output_tokens", 0) or 0

            self._counted_external_source_ids.add(source_id)
            self._total_input_tokens += input_tk
            self._total_output_tokens += output_tk
            self._total_tokens += total_tk

            caller = str(record.get("caller", ""))
            if caller.startswith("subagent:"):
                self._subagent_tokens += total_tk
            elif caller.startswith("middleware:"):
                self._middleware_tokens += total_tk
            else:
                self._lead_agent_tokens += total_tk

            cache_read_tk = record.get("cache_read_tokens", 0) or 0
            self._record_model_usage(record.get("model_name"), input_tk, output_tk, total_tk, int(cache_read_tk))

            self._schedule_progress_flush()

    def set_first_human_message(self, content: str) -> None:
        '''

        保存本轮首条用户消息的摘要字段。'''
        self._first_human_msg = content[:2000] if content else None

    def record_middleware(self, tag: str, *, name: str, hook: str, action: str, changes: dict) -> None:
        '''

        记录中间件状态变更事件。

                中间件执行有实际意义的状态变更（如生成标题、摘要或人工审批）时
                调用本方法；仅观察状态的中间件不应调用。

                Args:
                    tag: 中间件的短标识（如 "title"、"summarize"、
                         "guardrail"），用于构造 event_type="middleware:{tag}"。
                    name: 中间件的完整类名。
                    hook: 触发动作的生命周期钩子（如 "after_model"）。
                    action: 执行的具体动作（如 "generate_title"）。
                    changes: 描述所做状态变更的字典。
        '''
        self._put(
            event_type=f"middleware:{tag}",
            category="middleware",
            content={"name": name, "hook": hook, "action": action, "changes": changes},
        )

    def record_memory_context(self, *, content_sha256: str) -> None:
        '''

        记录本次运行实际使用的隐藏记忆块标识。

                完整记忆块已保存在检查点状态中，且可能包含用户数据，
                因而事件仅保存其精确的内容哈希。维护人员可通过现有运行事件
                调试接口比较各次运行实际使用的记忆，无需复制记忆内容。
        '''
        if self._memory_context_recorded:
            return
        self._put(
            event_type="context:memory",
            category="context",
            content={"content_sha256": content_sha256},
        )
        self._memory_context_recorded = True

    async def flush(self) -> None:
        '''

        等待已启动的写入任务，并强制刷新运行结束前剩余的事件。'''
        if self._pending_flush_tasks:
            await asyncio.gather(*tuple(self._pending_flush_tasks), return_exceptions=True)
        while self._pending_progress_task is not None and not self._pending_progress_task.done():
            if self._pending_progress_delayed:
                self._pending_progress_task.cancel()
                await asyncio.gather(self._pending_progress_task, return_exceptions=True)
                self._progress_dirty = False
                self._pending_progress_delayed = False
                break
            await asyncio.gather(self._pending_progress_task, return_exceptions=True)

        while self._buffer:
            batch = self._buffer[: self._flush_threshold]
            del self._buffer[: self._flush_threshold]
            try:
                await self._store.put_batch(batch)
            except Exception:
                self._buffer = batch + self._buffer
                raise

    def _schedule_progress_flush(self) -> None:
        '''

        节流安排运行统计快照上报，避免每次模型响应都触发写入。'''
        if self._progress_reporter is None:
            return
        now = time.monotonic()
        elapsed = now - self._last_progress_flush
        if elapsed < self._progress_flush_interval:
            self._progress_dirty = True
            self._schedule_delayed_progress_flush(self._progress_flush_interval - elapsed)
            return
        if self._pending_progress_task is not None and not self._pending_progress_task.done():
            self._progress_dirty = True
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._progress_dirty = False
        self._pending_progress_task = loop.create_task(self._flush_progress_async(snapshot=self.get_completion_data()))

    def _schedule_delayed_progress_flush(self, delay: float) -> None:
        '''安排延迟的运行进度快照写入，并避免重复创建刷新任务。'''
        if self._pending_progress_task is not None and not self._pending_progress_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        delay = max(0.0, delay)
        self._pending_progress_delayed = delay > 0
        self._pending_progress_task = loop.create_task(self._flush_progress_async(delay=delay))

    async def _flush_progress_async(self, *, snapshot: dict | None = None, delay: float = 0.0) -> None:
        '''按节流策略上报运行统计快照，并在期间有新变化时安排下一次刷新。'''
        if self._progress_reporter is None:
            return
        if delay > 0:
            self._pending_progress_delayed = True
            await asyncio.sleep(delay)
            self._pending_progress_delayed = False
        dirty_before_write = self._progress_dirty
        self._progress_dirty = False
        snapshot_to_write = snapshot or self.get_completion_data()
        try:
            await self._progress_reporter(snapshot_to_write)
            self._last_progress_flush = time.monotonic()
        except Exception:
            logger.warning("Failed to persist progress snapshot for run %s", self.run_id, exc_info=True)
        if dirty_before_write or self._progress_dirty:
            self._progress_dirty = False
            self._pending_progress_task = None
            self._schedule_delayed_progress_flush(self._progress_flush_interval)

    def get_completion_data(self) -> dict:
        '''

        返回运行完成时所需的累计令牌及消息统计数据。'''
        return {
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_tokens": self._total_tokens,
            "llm_call_count": self._llm_call_count,
            "lead_agent_tokens": self._lead_agent_tokens,
            "subagent_tokens": self._subagent_tokens,
            "middleware_tokens": self._middleware_tokens,
            "token_usage_by_model": {model: dict(usage) for model, usage in self._tokens_by_model.items()},
            "message_count": self._msg_count,
            "last_ai_message": self._last_ai_msg,
            "first_human_message": self._first_human_msg,
        }

    @property
    def had_llm_error_fallback(self) -> bool:
        '''指示本次运行是否曾使用模型错误回退响应。'''
        return self._had_llm_error_fallback

    @property
    def llm_error_fallback_message(self) -> str | None:
        '''返回本次运行最近记录的模型错误说明。'''
        return self._llm_error_fallback_message
