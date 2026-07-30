'定义 todo_middleware 模块提供的职责与可复用接口。\n\nMiddleware that extends TodoListMiddleware with context-loss detection and premature-exit prevention.\n\nWhen the message history is truncated (e.g., by SummarizationMiddleware), the\noriginal `write_todos` tool call and its ToolMessage can be scrolled out of the\nactive context window. This middleware detects that situation and injects a\nreminder message so the model still knows about the outstanding todo list.\n\nAdditionally, this middleware prevents the agent from exiting the loop while\nthere are still incomplete todo items. When the model produces a final response\n(no tool calls) but todos are not yet complete, the middleware queues a reminder\nfor the next model request and jumps back to the model node to force continued\nengagement. The completion reminder is injected via ``wrap_model_call`` instead\nof being persisted into graph state as a normal user-visible message.\n'

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.todo import Todo
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse, hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ThreadState


def _todos_in_messages(messages: list[Any]) -> bool:
    '执行 _todos_in_messages 的明确职责，并返回与调用约定一致的结果。\n\nReturn True if any AIMessage in *messages* contains a write_todos tool call.'
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("name") == "write_todos":
                    return True
    return False


def _reminder_in_messages(messages: list[Any]) -> bool:
    '执行 _reminder_in_messages 的明确职责，并返回与调用约定一致的结果。\n\nReturn True if a todo_reminder HumanMessage is already present in *messages*.'
    for msg in messages:
        if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == "todo_reminder":
            return True
    return False


def _format_todos(todos: list[Todo]) -> str:
    '执行 _format_todos 的明确职责，并返回与调用约定一致的结果。\n\nFormat a list of Todo items into a human-readable string.'
    lines: list[str] = []
    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        lines.append(f"- [{status}] {content}")
    return "\n".join(lines)


def _format_completion_reminder(todos: list[Todo]) -> str:
    '执行 _format_completion_reminder 的明确职责，并返回与调用约定一致的结果。\n\nFormat a completion reminder for incomplete todo items.'
    incomplete = [t for t in todos if t.get("status") != "completed"]
    incomplete_text = "\n".join(f"- [{t.get('status', 'pending')}] {t.get('content', '')}" for t in incomplete)
    return (
        "<system_reminder>\n"
        "You have incomplete todo items that must be finished before giving your final response:\n\n"
        f"{incomplete_text}\n\n"
        "Please continue working on these tasks. Call `write_todos` to mark items as completed "
        "as you finish them, and only respond when all items are done.\n"
        "</system_reminder>"
    )


_TOOL_CALL_FINISH_REASONS = {"tool_calls", "function_call"}


def _has_tool_call_intent_or_error(message: AIMessage) -> bool:
    '执行 _has_tool_call_intent_or_error 的明确职责，并返回与调用约定一致的结果。\n\nReturn True when an AIMessage is not a clean final answer.\n\n    Todo completion reminders should only fire when the model has produced a\n    plain final response. Provider/tool parsing details have moved across\n    LangChain versions and integrations, so keep all tool-intent/error signals\n    behind this helper instead of checking one concrete field at the call site.\n    '
    if message.tool_calls:
        return True

    if getattr(message, "invalid_tool_calls", None):
        return True

    # Backward/provider compatibility: some integrations preserve raw or legacy
    # tool-call intent in additional_kwargs even when structured tool_calls is
    # empty. If this helper changes, update the matching sentinel test
    # `TestToolCallIntentOrError.test_langchain_ai_message_tool_fields_are_explicitly_handled`;
    # if that test fails after a LangChain upgrade, review this helper so new
    # tool-call/error fields are not silently treated as clean final answers.
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    if additional_kwargs.get("tool_calls") or additional_kwargs.get("function_call"):
        return True

    response_metadata = getattr(message, "response_metadata", {}) or {}
    return response_metadata.get("finish_reason") in _TOOL_CALL_FINISH_REASONS


class TodoMiddleware(TodoListMiddleware):
    '封装 TodoMiddleware 的状态、协作关系与公开操作。\n\nExtends TodoListMiddleware with `write_todos` context-loss detection.\n\n    When the original `write_todos` tool call has been truncated from the message\n    history (e.g., after summarization), the model loses awareness of the current\n    todo list. This middleware detects that gap in `before_model` / `abefore_model`\n    and injects a reminder message so the model can continue tracking progress.\n    '

    state_schema = ThreadState

    @override
    def before_model(
        self,
        state: ThreadState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        '执行 before_model 的明确职责，并返回与调用约定一致的结果。\n\nInject a todo-list reminder when write_todos has left the context window.'
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        if not todos:
            return None

        messages = state.get("messages") or []
        if _todos_in_messages(messages):
            # write_todos is still visible in context — nothing to do.
            return None

        if _reminder_in_messages(messages):
            # A reminder was already injected and hasn't been truncated yet.
            return None

        # The todo list exists in state but the original write_todos call is gone.
        # Inject a reminder as a HumanMessage so the model stays aware.
        formatted = _format_todos(todos)
        reminder = HumanMessage(
            name="todo_reminder",
            additional_kwargs={"hide_from_ui": True},
            content=(
                "<system_reminder>\n"
                "Your todo list from earlier is no longer visible in the current context window, "
                "but it is still active. Here is the current state:\n\n"
                f"{formatted}\n\n"
                "Continue tracking and updating this todo list as you work. "
                "Call `write_todos` whenever the status of any item changes.\n"
                "</system_reminder>"
            ),
        )
        return {"messages": [reminder]}

    @override
    async def abefore_model(
        self,
        state: ThreadState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        '执行 abefore_model 的明确职责，并返回与调用约定一致的结果。\n\nAsync version of before_model.'
        return self.before_model(state, runtime)

    # Maximum number of completion reminders before allowing the agent to exit.
    # This prevents infinite loops when the agent cannot make further progress.
    _MAX_COMPLETION_REMINDERS = 2
    # Hard cap for per-run reminder bookkeeping in long-lived middleware instances.
    _MAX_COMPLETION_REMINDER_KEYS = 4096

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()
        self._pending_completion_reminders: dict[tuple[str, str], list[str]] = {}
        self._completion_reminder_counts: dict[tuple[str, str], int] = {}
        self._completion_reminder_touch_order: dict[tuple[str, str], int] = {}
        self._completion_reminder_next_order = 0

    @staticmethod
    def _get_thread_id(runtime: Runtime) -> str:
        '执行 _get_thread_id 的明确职责，并返回与调用约定一致的结果'
        context = getattr(runtime, "context", None)
        thread_id = context.get("thread_id") if context else None
        return str(thread_id) if thread_id else "default"

    @staticmethod
    def _get_run_id(runtime: Runtime) -> str:
        '执行 _get_run_id 的明确职责，并返回与调用约定一致的结果'
        context = getattr(runtime, "context", None)
        run_id = context.get("run_id") if context else None
        return str(run_id) if run_id else "default"

    def _pending_key(self, runtime: Runtime) -> tuple[str, str]:
        '执行 _pending_key 的明确职责，并返回与调用约定一致的结果'
        return self._get_thread_id(runtime), self._get_run_id(runtime)

    def _touch_completion_reminder_key_locked(self, key: tuple[str, str]) -> None:
        '执行 _touch_completion_reminder_key_locked 的明确职责，并返回与调用约定一致的结果'
        self._completion_reminder_next_order += 1
        self._completion_reminder_touch_order[key] = self._completion_reminder_next_order

    def _completion_reminder_keys_locked(self) -> set[tuple[str, str]]:
        '执行 _completion_reminder_keys_locked 的明确职责，并返回与调用约定一致的结果'
        keys = set(self._pending_completion_reminders)
        keys.update(self._completion_reminder_counts)
        keys.update(self._completion_reminder_touch_order)
        return keys

    def _drop_completion_reminder_key_locked(self, key: tuple[str, str]) -> None:
        '执行 _drop_completion_reminder_key_locked 的明确职责，并返回与调用约定一致的结果'
        self._pending_completion_reminders.pop(key, None)
        self._completion_reminder_counts.pop(key, None)
        self._completion_reminder_touch_order.pop(key, None)

    def _prune_completion_reminder_state_locked(self, protected_key: tuple[str, str]) -> None:
        '执行 _prune_completion_reminder_state_locked 的明确职责，并返回与调用约定一致的结果'
        keys = self._completion_reminder_keys_locked()
        overflow = len(keys) - self._MAX_COMPLETION_REMINDER_KEYS
        if overflow <= 0:
            return

        candidates = [key for key in keys if key != protected_key]
        candidates.sort(key=lambda key: self._completion_reminder_touch_order.get(key, 0))
        for key in candidates[:overflow]:
            self._drop_completion_reminder_key_locked(key)

    def _queue_completion_reminder(self, runtime: Runtime, reminder: str) -> None:
        '执行 _queue_completion_reminder 的明确职责，并返回与调用约定一致的结果'
        key = self._pending_key(runtime)
        with self._lock:
            self._pending_completion_reminders.setdefault(key, []).append(reminder)
            self._completion_reminder_counts[key] = self._completion_reminder_counts.get(key, 0) + 1
            self._touch_completion_reminder_key_locked(key)
            self._prune_completion_reminder_state_locked(protected_key=key)

    def _completion_reminder_count_for_runtime(self, runtime: Runtime) -> int:
        '执行 _completion_reminder_count_for_runtime 的明确职责，并返回与调用约定一致的结果'
        key = self._pending_key(runtime)
        with self._lock:
            return self._completion_reminder_counts.get(key, 0)

    def _drain_completion_reminders(self, runtime: Runtime) -> list[str]:
        '执行 _drain_completion_reminders 的明确职责，并返回与调用约定一致的结果'
        key = self._pending_key(runtime)
        with self._lock:
            reminders = self._pending_completion_reminders.pop(key, [])
            if reminders or key in self._completion_reminder_counts:
                self._touch_completion_reminder_key_locked(key)
            return reminders

    def _clear_other_run_completion_reminders(self, runtime: Runtime) -> None:
        '执行 _clear_other_run_completion_reminders 的明确职责，并返回与调用约定一致的结果'
        thread_id, current_run_id = self._pending_key(runtime)
        with self._lock:
            for key in self._completion_reminder_keys_locked():
                if key[0] == thread_id and key[1] != current_run_id:
                    self._drop_completion_reminder_key_locked(key)

    def _clear_current_run_completion_reminders(self, runtime: Runtime) -> None:
        '执行 _clear_current_run_completion_reminders 的明确职责，并返回与调用约定一致的结果'
        key = self._pending_key(runtime)
        with self._lock:
            self._drop_completion_reminder_key_locked(key)

    @override
    def before_agent(self, state: ThreadState, runtime: Runtime) -> dict[str, Any] | None:
        '执行 before_agent 的明确职责，并返回与调用约定一致的结果'
        self._clear_other_run_completion_reminders(runtime)
        return None

    @override
    async def abefore_agent(self, state: ThreadState, runtime: Runtime) -> dict[str, Any] | None:
        '执行 abefore_agent 的明确职责，并返回与调用约定一致的结果'
        self._clear_other_run_completion_reminders(runtime)
        return None

    @hook_config(can_jump_to=["model"])
    @override
    def after_model(
        self,
        state: ThreadState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        '执行 after_model 的明确职责，并返回与调用约定一致的结果。\n\nPrevent premature agent exit when todo items are still incomplete.\n\n        In addition to the base class check for parallel ``write_todos`` calls,\n        this override intercepts model responses that have no tool calls while\n        there are still incomplete todo items. It injects a reminder\n        ``HumanMessage`` and jumps back to the model node so the agent\n        continues working through the todo list.\n\n        A retry cap of ``_MAX_COMPLETION_REMINDERS`` (default 2) prevents\n        infinite loops when the agent cannot make further progress.\n        '
        # 1. Preserve base class logic (parallel write_todos detection).
        base_result = super().after_model(state, runtime)
        if base_result is not None:
            return base_result

        # 2. Only intervene when the agent wants to exit cleanly. Tool-call
        # intent or tool-call parse errors should be handled by the tool path
        # instead of being masked by todo reminders.
        messages = state.get("messages") or []
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if not last_ai or _has_tool_call_intent_or_error(last_ai):
            return None

        # 3. Allow exit when all todos are completed or there are no todos.
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        if not todos or all(t.get("status") == "completed" for t in todos):
            return None

        # 4. Enforce a reminder cap to prevent infinite re-engagement loops.
        if self._completion_reminder_count_for_runtime(runtime) >= self._MAX_COMPLETION_REMINDERS:
            return None

        # 5. Queue a reminder for the next model request and jump back. We must
        # not persist this control prompt as a normal HumanMessage, otherwise it
        # can leak into user-visible message streams and saved transcripts.
        self._queue_completion_reminder(runtime, _format_completion_reminder(todos))
        return {"jump_to": "model"}

    @override
    @hook_config(can_jump_to=["model"])
    async def aafter_model(
        self,
        state: ThreadState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        '执行 aafter_model 的明确职责，并返回与调用约定一致的结果。\n\nAsync version of after_model.'
        return self.after_model(state, runtime)

    @staticmethod
    def _format_pending_completion_reminders(reminders: list[str]) -> str:
        '执行 _format_pending_completion_reminders 的明确职责，并返回与调用约定一致的结果'
        return "\n\n".join(dict.fromkeys(reminders))

    def _augment_request(self, request: ModelRequest) -> ModelRequest:
        '执行 _augment_request 的明确职责，并返回与调用约定一致的结果'
        reminders = self._drain_completion_reminders(request.runtime)
        if not reminders:
            return request
        new_messages = [
            *request.messages,
            HumanMessage(
                content=self._format_pending_completion_reminders(reminders),
                name="todo_completion_reminder",
                additional_kwargs={"hide_from_ui": True},
            ),
        ]
        return request.override(messages=new_messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        '执行 wrap_model_call 的明确职责，并返回与调用约定一致的结果'
        return handler(self._augment_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        '执行 awrap_model_call 的明确职责，并返回与调用约定一致的结果'
        return await handler(self._augment_request(request))

    @override
    def after_agent(self, state: ThreadState, runtime: Runtime) -> dict[str, Any] | None:
        '执行 after_agent 的明确职责，并返回与调用约定一致的结果'
        self._clear_current_run_completion_reminders(runtime)
        return None

    @override
    async def aafter_agent(self, state: ThreadState, runtime: Runtime) -> dict[str, Any] | None:
        '执行 aafter_agent 的明确职责，并返回与调用约定一致的结果'
        self._clear_current_run_completion_reminders(runtime)
        return None
