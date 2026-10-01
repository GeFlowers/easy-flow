'''跟踪工具结果是否持续产生新信息，并在反复停滞时提示模型或阻止重复调用。

Middleware for task-level tool call progress tracking with a state machine.

Implements RFC #3177: structured tool result signals drive a per-(thread, tool)
state machine that detects stagnation and repetition, injects hints early
(WARNED), and hard-blocks the tool when it has stopped producing value (BLOCKED).

Architecture:
  ToolProgressMiddleware (outer)
    └── handler → ToolErrorHandlingMiddleware (inner) → actual tool
                                                              ↓
  ToolProgressMiddleware reads deerflow_tool_meta from the normalized result

State machine transitions per (thread_id, tool_name):
  ACTIVE → WARNED (at stagnation_threshold problems)
  Any problem-free call resets consecutive_problems=0 and reverts to ACTIVE.

  Whether WARNED can escalate to BLOCKED depends on recoverable_by_model:
  - recoverable_by_model=True  (no_results, not_found, permission, Jaccard-duplicate success):
      WARNED is terminal. The model received a hint and is expected to change strategy;
      blocking would prevent a legitimate retry with different parameters.
  - recoverable_by_model=False, action≠stop (transient, rate_limited):
      WARNED → BLOCKED after warn_escalation_count more problems. The model cannot fix
      these by retrying the same tool, so hard-blocking conserves API calls.
  - recoverable_by_model=False, action=stop (auth, config, internal):
      Immediately BLOCKED on the first occurrence — no retry can help.

Division of labor with LoopDetectionMiddleware (middleware position 23):
  ToolProgressMiddleware (position 10) is a result-quality guard — it fires
  after a tool executes, inspects what came back, and blocks *specific tools*
  that have stopped producing new information.

  LoopDetectionMiddleware is a call-pattern guard — it fires after the model
  responds (before tools execute), inspects the tool_calls signature in the
  AIMessage, and forces the *whole turn* to stop when the model keeps issuing
  the same calls regardless of results.

  They are complementary, not competing:
  - ToolProgressMiddleware is fine-grained (per-tool BLOCK, other tools normal).
  - LoopDetectionMiddleware is coarse-grained (strips all tool_calls, ends turn).
  - Both can inject HumanMessage hints in the same model call without conflict;
    the model sees both sets of hints and can reason about them.
  - If LoopDetectionMiddleware hard-stops (strips tool_calls), no wrap_tool_call
    is issued so ToolProgressMiddleware never fires — there is no double-stop.
  - If ToolProgressMiddleware BLOCKs a tool (returns an error ToolMessage),
    the model still makes a tool call that LoopDetectionMiddleware tracks; both
    continue to operate on their own independent state.
'''

from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict, defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, ToolResultMeta

if TYPE_CHECKING:
    from deerflow.config.tool_progress_config import ToolProgressConfig

logger = logging.getLogger(__name__)

_MAX_PENDING_PER_RUN = 3
# 限制文本长度，避免对大型工具结果执行无界正则和集合运算。
_MAX_CONTENT_FOR_WORDSET = 8192


# 状态数据结构


@dataclass(slots=True)
class ToolPhaseState:
    '''保存单个线程与工具的阶段、连续问题数、屏蔽原因和近期结果词集。'''

    phase: Literal["active", "warned", "blocked"] = "active"
    consecutive_problems: int = 0
    block_reason: str | None = None
    # 使用不可变元组，避免 replace 创建的新旧状态意外共享可变列表。
    recent_word_sets: tuple[frozenset[str], ...] = field(default_factory=tuple)


# 内容相似度辅助函数


def word_set(content: str) -> frozenset[str]:
    '''提取结果中的小写词集合，用于近似重复检测，并限制参与计算的文本长度。'''
    return frozenset(re.findall(r"\b\w{3,}\b", content[:_MAX_CONTENT_FOR_WORDSET].lower()))


def is_near_duplicate(
    current: frozenset[str],
    recent: Sequence[frozenset[str]],
    threshold: float,
    min_words: int,
) -> bool:
    '''用 Jaccard 相似度比较最近三次结果；词数不足时不判为重复。'''
    if len(current) < min_words:
        return False
    for prev in recent[-3:]:
        if len(prev) < min_words:
            continue
        union = len(current | prev)
        if union == 0:
            continue
        if len(current & prev) / union >= threshold:
            return True
    return False


def _message_content_str(msg: ToolMessage) -> str:
    '''仅当工具消息内容为字符串时返回正文，其他内容视为空文本。'''
    return msg.content if isinstance(msg.content, str) else ""


def _parse_tool_meta(meta_dict: object) -> ToolResultMeta | None:
    '''将原始元数据解析为 ToolResultMeta；结构异常时跳过进度跟踪。'''
    if not isinstance(meta_dict, dict):
        return None
    try:
        return ToolResultMeta(**meta_dict)
    except TypeError:
        logger.warning("Unexpected tool meta schema, skipping progress tracking: %s", meta_dict)
        return None


# 提示和屏蔽原因格式化


def _format_hint(meta: ToolResultMeta) -> str:
    '''根据结果类型和建议动作生成供模型调整策略的提示。'''
    action_map = {
        "rewrite_query": "Try rephrasing your search query with different keywords or approach.",
        "try_alternative": "Consider using a different tool or strategy.",
        "summarize": "Consider summarizing your current findings and moving forward.",
        "stop": "Do not retry this operation — it is not recoverable.",
        # 结果虽成功但内容近似重复，仍需建议模型更换检索策略。
        "continue": "Try rephrasing your query or using a different search term.",
    }
    base = {
        "no_results": "[PROGRESS HINT] Your search returned no results.",
        "not_found": "[PROGRESS HINT] The resource was not found repeatedly.",
        "rate_limited": "[PROGRESS HINT] The tool is being rate-limited.",
        "transient": "[PROGRESS HINT] The tool encountered repeated transient failures.",
        "partial_success": "[PROGRESS HINT] The tool has returned incomplete results multiple times.",
        # 近似重复的成功结果表示工具反复返回相同内容。
        "success": "[PROGRESS HINT] The tool is returning duplicate results.",
    }.get(
        meta.error_type or meta.status,
        "[PROGRESS HINT] The tool is not producing new information.",
    )
    suffix = action_map.get(meta.recommended_next_action, "")
    return f"{base} {suffix}".strip()


def _block_reason(meta: ToolResultMeta) -> str:
    '''把错误类别转换为工具被屏蔽时返回给模型的原因。'''
    return {
        "no_results": "Repeated no-results — rewrite your query or try a different tool.",
        "not_found": "Repeated not-found — rewrite your query or try a different resource.",
        "rate_limited": "Repeated rate-limiting — summarize current findings and proceed.",
        "transient": "Repeated transient failures — try a different approach.",
        "auth": "Authentication failure — this tool cannot be used.",
        "config": "Tool is not configured — this tool cannot be used.",
        "internal": "Repeated internal errors — this tool is unavailable.",
    }.get(
        meta.error_type or "",
        "Tool has not produced new information after multiple attempts — summarize and move on.",
    )


# 中间件实现


class ToolProgressMiddleware(AgentMiddleware[AgentState]):
    '''根据工具结果更新停滞状态，在无进展时注入提示或返回屏蔽消息。'''

    def __init__(
        self,
        *,
        stagnation_threshold: int = 3,
        warn_escalation_count: int = 2,
        inject_assessment: bool = True,
        jaccard_threshold: float = 0.8,
        min_words: int = 10,
        exempt_tools: set[str] | None = None,
        max_tracked_threads: int = 100,
    ) -> None:
        '''保存停滞和相似度阈值，并初始化线程状态表与运行级提示队列。'''
        self._stagnation_threshold = stagnation_threshold
        self._warn_escalation = warn_escalation_count
        self._inject_assessment = inject_assessment
        self._jaccard_threshold = jaccard_threshold
        self._min_words = min_words
        self._exempt_tools: set[str] = exempt_tools if exempt_tools is not None else {"ask_clarification", "write_todos", "present_files", "task"}
        self._max_tracked_threads = max_tracked_threads

        # 临界区只操作内存，线程锁可以同时保护同步子代理和异步 Gateway 调用。
        self._lock = threading.Lock()
        # 按线程 LRU 淘汰的状态表：线程 ID → 工具名 → 阶段状态。
        self._phase_states: OrderedDict[str, dict[str, ToolPhaseState]] = OrderedDict()
        # 按线程和运行隔离的待注入提示队列。
        self._pending: dict[tuple[str, str], list[str]] = defaultdict(list)

    @classmethod
    def from_config(cls, config: ToolProgressConfig) -> ToolProgressMiddleware:
        '''将配置字段映射为中间件参数，并复制豁免工具集合。'''
        return cls(
            stagnation_threshold=config.stagnation_threshold,
            warn_escalation_count=config.warn_escalation_count,
            inject_assessment=config.inject_assessment,
            jaccard_threshold=config.jaccard_similarity_threshold,
            min_words=config.min_word_count_for_similarity,
            exempt_tools=set(config.exempt_tools),
            max_tracked_threads=config.max_tracked_threads,
        )

    # 运行上下文辅助函数

    @staticmethod
    def _thread_id(runtime: Runtime) -> str:
        '''读取运行上下文的线程 ID；缺失时归入默认线程。'''
        tid = runtime.context.get("thread_id") if runtime.context else None
        return str(tid) if tid else "default"

    @staticmethod
    def _run_id(runtime: Runtime) -> str:
        '''读取运行上下文的运行 ID；缺失时归入默认运行。'''
        rid = runtime.context.get("run_id") if runtime.context else None
        return str(rid) if rid else "default"

    def _pending_key(self, runtime: Runtime) -> tuple[str, str]:
        '''组合线程和运行标识，隔离各轮待注入提示。'''
        return self._thread_id(runtime), self._run_id(runtime)

    # 状态存储（调用方负责持锁）

    def _get_state(self, thread_id: str, tool_name: str) -> ToolPhaseState:
        '''读取工具状态；首次访问时创建线程记录并按容量淘汰最久未用线程。'''
        if thread_id not in self._phase_states:
            self._phase_states[thread_id] = {}
            while len(self._phase_states) > self._max_tracked_threads:
                evicted_thread, _ = self._phase_states.popitem(last=False)
                # 线程状态被淘汰时同步清除其提示队列，避免残留占用。
                for key in [k for k in self._pending if k[0] == evicted_thread]:
                    del self._pending[key]
        self._phase_states.move_to_end(thread_id)
        return self._phase_states[thread_id].get(tool_name, ToolPhaseState())

    def _set_state(self, thread_id: str, tool_name: str, state: ToolPhaseState) -> None:
        '''保存指定线程中某个工具的新阶段状态。调用方须持锁。'''
        self._phase_states[thread_id][tool_name] = state

    def _get_block_reason(self, runtime: Runtime, tool_name: str) -> str | None:
        '''只读检查工具是否已被屏蔽；读取不更新 LRU 顺序。'''
        thread_id = self._thread_id(runtime)
        with self._lock:
            thread_tools = self._phase_states.get(thread_id)
            if thread_tools is None:
                return None
            # 被屏蔽线程的查询不能续期，否则会挤占仍活跃线程的状态容量。
            tool_state = thread_tools.get(tool_name)
            return tool_state.block_reason if tool_state is not None and tool_state.phase == "blocked" else None

    def _make_blocked_message(self, request: ToolCallRequest, tool_name: str, block_reason: str) -> ToolMessage:
        '''构造与原工具调用 ID 配对的错误 ToolMessage，并附上可恢复提示元数据。'''
        return ToolMessage(
            content=f"[TOOL_BLOCKED] {block_reason}",
            tool_call_id=str(request.tool_call.get("id", "")),
            name=tool_name,
            status="error",
            additional_kwargs={
                TOOL_META_KEY: {
                    "status": "error",
                    "error_type": "blocked_by_progress_guard",
                    "recoverable_by_model": True,
                    "recommended_next_action": "summarize",
                    "source": "progress_middleware",
                }
            },
        )

    def _update_state_from_result(
        self,
        result: ToolMessage | Command,
        tool_name: str,
        runtime: Runtime,
    ) -> ToolMessage | Command:
        '''解析工具结果元数据并更新阶段状态；达到提示条件时排入本轮提示队列。'''
        if not isinstance(result, ToolMessage):
            return result
        meta = _parse_tool_meta((result.additional_kwargs or {}).get(TOOL_META_KEY))
        if meta is None:
            if tool_name not in self._exempt_tools:
                logger.warning(
                    "tool_progress: deerflow_tool_meta missing for non-exempt tool %s — verify ToolProgressMiddleware is outer of ToolErrorHandlingMiddleware",
                    tool_name,
                )
            return result
        content = _message_content_str(result)
        thread_id = self._thread_id(runtime)
        with self._lock:
            state = self._get_state(thread_id, tool_name)
            new_state, hint = self._assess_and_transition(state, meta, content)
            self._set_state(thread_id, tool_name, new_state)
        if new_state.phase != state.phase:
            if new_state.phase == "blocked":
                logger.warning(
                    "tool_progress: %s/%s -> BLOCKED: %s",
                    thread_id,
                    tool_name,
                    new_state.block_reason,
                )
            elif new_state.phase == "warned":
                logger.info(
                    "tool_progress: %s/%s -> WARNED (consecutive_problems=%d)",
                    thread_id,
                    tool_name,
                    new_state.consecutive_problems,
                )
            elif new_state.phase == "active":
                logger.info(
                    "tool_progress: %s/%s -> ACTIVE (reset after good result)",
                    thread_id,
                    tool_name,
                )
        if hint and self._inject_assessment:
            self._queue_assessment(runtime, hint)
        return result

    # 状态转换逻辑

    def _assess_and_transition(
        self,
        state: ToolPhaseState,
        meta: ToolResultMeta,
        content: str,
    ) -> tuple[ToolPhaseState, str | None]:
        '''按结果可恢复性、连续问题次数及重复度计算新状态和可选提示。'''
        # BLOCKED 是终态；并发状态变化时不允许后续结果将其降级。
        if state.phase == "blocked":
            return state, None

        # 先统一累计问题次数，确保所有失败分支保留一致计数。
        new_count = state.consecutive_problems + 1

        # 认证、配置和内部错误等不可恢复问题无需重试，立即屏蔽工具。
        if not meta.recoverable_by_model and meta.recommended_next_action == "stop":
            return replace(
                state,
                phase="blocked",
                consecutive_problems=new_count,
                block_reason=_block_reason(meta),
            ), None

        # 只有成功结果需要计算词集；错误和部分成功本身已构成问题。
        ws = word_set(content) if meta.status == "success" else frozenset()
        is_problem = meta.status in ("error", "partial_success") or (meta.status == "success" and is_near_duplicate(ws, state.recent_word_sets, self._jaccard_threshold, self._min_words))

        if not is_problem:
            # 新结果有进展时清零连续问题数，并记录近期内容供去重判断。
            new_recent = (*state.recent_word_sets, ws)[-3:]
            return replace(state, consecutive_problems=0, phase="active", recent_word_sets=new_recent), None

        hint: str | None = None

        if new_count >= self._stagnation_threshold + self._warn_escalation:
            if meta.recoverable_by_model:
                # 模型可通过换策略恢复，继续提示而不屏蔽不同参数的合理重试。
                hint = _format_hint(meta)
                new_state = replace(state, consecutive_problems=new_count, phase="warned")
            else:
                # 模型无法靠重试改变故障，停止对该工具继续发起请求。
                reason = _block_reason(meta)
                new_state = replace(state, consecutive_problems=new_count, phase="blocked", block_reason=reason)
        elif new_count >= self._stagnation_threshold:
            hint = _format_hint(meta)
            new_state = replace(state, consecutive_problems=new_count, phase="warned")
        else:
            new_state = replace(state, consecutive_problems=new_count)

        return new_state, hint

    # 待发送提示队列

    def _queue_assessment(self, runtime: Runtime, text: str) -> None:
        '''为当前运行暂存状态提示，并限制每轮提示数量。'''
        key = self._pending_key(runtime)
        thread_id = key[0]
        with self._lock:
            # 状态已被 LRU 淘汰时不创建后续淘汰逻辑无法清理的孤立提示队列。
            if thread_id not in self._phase_states:
                return
            queue = self._pending[key]
            if len(queue) < _MAX_PENDING_PER_RUN:
                queue.append(text)

    def _drain_pending(self, runtime: Runtime) -> list[str]:
        '''取出并删除当前运行待注入的全部提示。'''
        key = self._pending_key(runtime)
        with self._lock:
            return self._pending.pop(key, [])

    def _clear_stale_pending(self, runtime: Runtime) -> None:
        '''清除同线程其他运行遗留的提示，避免提示跨运行串用。'''
        thread_id, current_run = self._pending_key(runtime)
        with self._lock:
            for key in list(self._pending):
                if key[0] == thread_id and key[1] != current_run:
                    del self._pending[key]

    def _reset_run_states(self, runtime: Runtime) -> None:
        '''新一轮开始时重置该线程工具状态，避免上一轮暂时性故障造成错误屏蔽。'''
        thread_id = self._thread_id(runtime)
        with self._lock:
            thread_tools = self._phase_states.get(thread_id)
            if thread_tools is None:
                return
            for tool_name, tool_state in list(thread_tools.items()):
                thread_tools[tool_name] = replace(
                    tool_state,
                    phase="active",
                    consecutive_problems=0,
                    block_reason=None,
                    recent_word_sets=(),
                )

    # 工具调用钩子

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        '''同步工具调用前拦截已屏蔽工具，其余调用结果用于更新状态机。'''
        tool_name = str(request.tool_call.get("name", ""))
        if not tool_name or tool_name in self._exempt_tools:
            return handler(request)
        runtime = getattr(request, "runtime", None)
        if runtime is None:
            return handler(request)
        block_reason = self._get_block_reason(runtime, tool_name)
        if block_reason:
            logger.info(
                "tool_progress: %s/%s call intercepted (blocked): %s",
                self._thread_id(runtime),
                tool_name,
                block_reason,
            )
            return self._make_blocked_message(request, tool_name, block_reason)
        return self._update_state_from_result(handler(request), tool_name, runtime)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        '''异步工具调用前检查屏蔽状态，并在执行后跟踪工具结果。'''
        tool_name = str(request.tool_call.get("name", ""))
        if not tool_name or tool_name in self._exempt_tools:
            return await handler(request)
        runtime = getattr(request, "runtime", None)
        if runtime is None:
            return await handler(request)
        block_reason = self._get_block_reason(runtime, tool_name)
        if block_reason:
            logger.info(
                "tool_progress: %s/%s call intercepted (blocked): %s",
                self._thread_id(runtime),
                tool_name,
                block_reason,
            )
            return self._make_blocked_message(request, tool_name, block_reason)
        return self._update_state_from_result(await handler(request), tool_name, runtime)

    # 模型调用钩子：取出提示并在模型读取消息前追加

    def _augment_request(self, request: ModelRequest) -> ModelRequest:
        '''将本轮去重后的进展提示追加到模型请求末尾。'''
        hints = self._drain_pending(request.runtime)
        if not hints:
            return request
        deduped = list(dict.fromkeys(hints))
        logger.debug(
            "tool_progress: injecting %d hint(s) for %s/%s",
            len(deduped),
            *self._pending_key(request.runtime),
        )
        new_messages = [
            *request.messages,
            HumanMessage(content="\n\n".join(deduped), name="progress_hint"),
        ]
        return request.override(messages=new_messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        '''同步模型调用前注入工具进展提示，再调用下游处理器。'''
        return handler(self._augment_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        '''异步模型调用前注入工具进展提示，再等待下游处理器。'''
        return await handler(self._augment_request(request))

    # Agent 启动钩子：清理先前运行遗留的提示

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''每轮开始时清理旧提示并重置该线程的工具状态。'''
        self._clear_stale_pending(runtime)
        self._reset_run_states(runtime)
        return None

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''异步启动钩子执行与同步入口相同的状态清理。'''
        self._clear_stale_pending(runtime)
        self._reset_run_states(runtime)
        return None
