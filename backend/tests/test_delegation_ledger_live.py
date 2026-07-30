'定义 test_delegation_ledger_live 模块提供的职责与可复用接口。\n\nLive E2E coverage for delegation ledger crossing real summarization.\n\nRun explicitly with real credentials:\n\n    RUN_DEERFLOW_LEDGER_LIVE=1 PYTHONPATH=. uv run pytest tests/test_delegation_ledger_live.py -v -s\n'

from __future__ import annotations

import importlib
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.client import DeerFlowClient, StreamEvent
from deerflow.config.app_config import reload_app_config, reset_app_config, set_app_config

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROOT_CONFIG = _REPO_ROOT / "config.yaml"

_skip_reason = None
if os.environ.get("CI"):
    _skip_reason = "Live delegation ledger test skipped in CI"
elif os.environ.get("RUN_DEERFLOW_LEDGER_LIVE") != "1":
    _skip_reason = "Set RUN_DEERFLOW_LEDGER_LIVE=1 to run this real-model test"
elif not _ROOT_CONFIG.exists():
    _skip_reason = "No config.yaml found; live test requires real MiMo config"

if _skip_reason:
    pytest.skip(_skip_reason, allow_module_level=True)


class _RecordModelRequests(AgentMiddleware):
    '封装 _RecordModelRequests 的状态、协作关系与公开操作。\n\nRecord real model requests after ledger injection and system coalescing.'

    def __init__(self) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        super().__init__()
        self.calls: list[list[BaseMessage]] = []
        self.injected_calls: list[list[BaseMessage]] = []
        self.before_model_states: list[dict[str, Any]] = []

    def before_model(self, state: dict[str, Any], runtime: Runtime) -> None:
        '执行 before_model 的明确职责，并返回与调用约定一致的结果'
        messages = list(state.get("messages", []))
        snapshot = {
            "message_count": len(messages),
            "has_summary_message": any(getattr(message, "name", None) == "summary" for message in messages),
            "has_summary_text": bool(state.get("summary_text")),
            "ledger_count": len(state.get("delegations") or []),
            "skill_count": len(state.get("skill_context") or []),
        }
        self.before_model_states.append(snapshot)
        return None

    async def abefore_model(self, state: dict[str, Any], runtime: Runtime) -> None:
        '执行 abefore_model 的明确职责，并返回与调用约定一致的结果'
        self.before_model(state, runtime)
        return None

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        '执行 wrap_model_call 的明确职责，并返回与调用约定一致的结果'
        self.calls.append(list(request.messages))
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        '执行 awrap_model_call 的明确职责，并返回与调用约定一致的结果'
        self.calls.append(list(request.messages))
        return await handler(request)


@pytest.fixture
def live_config_path(tmp_path):
    '执行 live_config_path 的明确职责，并返回与调用约定一致的结果。\n\nCopy the real config and only lower summary threshold for deterministic E2E.'
    config = yaml.safe_load(_ROOT_CONFIG.read_text(encoding="utf-8"))
    config.setdefault("summarization", {})
    config["summarization"]["enabled"] = True
    config["summarization"]["trigger"] = [{"type": "messages", "value": 4}]
    config["summarization"]["keep"] = {"type": "messages", "value": 4}

    path = tmp_path / "config.live-ledger.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    set_app_config(reload_app_config(str(path)))
    yield str(path)
    reset_app_config()
    reload_app_config(str(_ROOT_CONFIG))


@pytest.fixture
def real_subagent_executor():
    "执行 real_subagent_executor 的明确职责，并返回与调用约定一致的结果。\n\nUndo tests/conftest.py's executor mock for this explicit live test."
    original_executor_module = sys.modules.get("deerflow.subagents.executor")
    original_subagent_attrs: dict[str, Any] = {}
    original_task_tool_attrs: dict[str, Any] = {}

    import deerflow.subagents as subagents_pkg

    for name in ("SubagentExecutor", "SubagentResult"):
        original_subagent_attrs[name] = getattr(subagents_pkg, name, None)

    sys.modules.pop("deerflow.subagents.executor", None)
    executor_module = importlib.import_module("deerflow.subagents.executor")
    subagents_pkg.SubagentExecutor = executor_module.SubagentExecutor
    subagents_pkg.SubagentResult = executor_module.SubagentResult

    task_tool_module = sys.modules.get("deerflow.tools.builtins.task_tool")
    if task_tool_module is not None:
        for name in (
            "SubagentExecutor",
            "SubagentStatus",
            "cleanup_background_task",
            "get_background_task_result",
            "request_cancel_background_task",
        ):
            original_task_tool_attrs[name] = getattr(task_tool_module, name, None)
            setattr(task_tool_module, name, getattr(executor_module, name))

    yield

    if original_executor_module is not None:
        sys.modules["deerflow.subagents.executor"] = original_executor_module
    else:
        sys.modules.pop("deerflow.subagents.executor", None)
    for name, value in original_subagent_attrs.items():
        setattr(subagents_pkg, name, value)
    if task_tool_module is not None:
        for name, value in original_task_tool_attrs.items():
            setattr(task_tool_module, name, value)


@pytest.fixture
def live_client(live_config_path, real_subagent_executor, monkeypatch):
    '执行 live_client 的明确职责，并返回与调用约定一致的结果'
    recorder = _RecordModelRequests()
    original_inject = DurableContextMiddleware._inject

    def recording_inject(self: DurableContextMiddleware, request: ModelRequest) -> ModelRequest:
        '执行 recording_inject 的明确职责，并返回与调用约定一致的结果'
        updated = original_inject(self, request)
        if updated is not request:
            recorder.injected_calls.append(list(updated.messages))
        return updated

    monkeypatch.setattr(DurableContextMiddleware, "_inject", recording_inject)
    client = DeerFlowClient(
        checkpointer=InMemorySaver(),
        thinking_enabled=False,
        subagent_enabled=True,
        middlewares=[recorder],
    )
    return client, recorder


def _message_text(message: BaseMessage) -> str:
    '执行 _message_text 的明确职责，并返回与调用约定一致的结果'
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content)


def _stream_events(client: DeerFlowClient, thread_id: str, prompt: str) -> list[StreamEvent]:
    '执行 _stream_events 的明确职责，并返回与调用约定一致的结果'
    events: list[StreamEvent] = []
    for event in client.stream(
        prompt,
        thread_id=thread_id,
        subagent_enabled=True,
        thinking_enabled=False,
        recursion_limit=180,
    ):
        events.append(event)
        if event.type == "messages-tuple" and event.data.get("type") in {"ai", "tool"}:
            print(f"[{event.data.get('type')}] {event.data}")
        elif event.type == "custom":
            print(f"[custom] {event.data}")
        elif event.type == "end":
            print(f"[end] {event.data}")
    return events


def _task_calls(events: list[StreamEvent]) -> list[dict[str, Any]]:
    '执行 _task_calls 的明确职责，并返回与调用约定一致的结果'
    calls: list[dict[str, Any]] = []
    for event in events:
        if event.type != "messages-tuple":
            continue
        data = event.data
        if data.get("type") != "ai":
            continue
        for call in data.get("tool_calls") or []:
            if call.get("name") == "task":
                calls.append(call)
    return calls


def _task_ids_in_state(values: dict[str, Any], task_ids: set[str]) -> set[str]:
    '执行 _task_ids_in_state 的明确职责，并返回与调用约定一致的结果'
    present: set[str] = set()
    for message in values.get("messages", []):
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                call_id = call.get("id")
                if call_id in task_ids:
                    present.add(call_id)
        elif isinstance(message, ToolMessage) and message.tool_call_id in task_ids:
            present.add(message.tool_call_id)
    return present


def _state_values(client: DeerFlowClient, thread_id: str) -> dict[str, Any]:
    '执行 _state_values 的明确职责，并返回与调用约定一致的结果'
    assert client._agent is not None
    config = client._get_runnable_config(
        thread_id,
        subagent_enabled=True,
        thinking_enabled=False,
        recursion_limit=180,
    )
    return client._agent.get_state(config).values


def _has_summary_message(values: dict[str, Any]) -> bool:
    '执行 _has_summary_message 的明确职责，并返回与调用约定一致的结果'
    return any(getattr(message, "name", None) == "summary" for message in values.get("messages", []))


def _summary_text(values: dict[str, Any]) -> str:
    '执行 _summary_text 的明确职责，并返回与调用约定一致的结果'
    return str(values.get("summary_text") or "").strip()


def _ledger_entries(values: dict[str, Any]) -> list[dict[str, Any]]:
    '执行 _ledger_entries 的明确职责，并返回与调用约定一致的结果'
    return list(values.get("delegations") or [])


def _skill_paths_in_state(values: dict[str, Any]) -> list[str]:
    '执行 _skill_paths_in_state 的明确职责，并返回与调用约定一致的结果'
    return [entry["path"] for entry in values.get("skill_context", [])]


def _ledger_visible_in_requests(requests: list[list[BaseMessage]], *, after_call_index: int = 0) -> bool:
    '执行 _ledger_visible_in_requests 的明确职责，并返回与调用约定一致的结果'
    for messages in requests[after_call_index:]:
        text = "\n".join(_message_text(message) for message in messages)
        if "Work already delegated" in text and "ledger alpha fact" in text and "ledger beta fact" in text:
            return True
    return False


def _summary_visible_in_requests(requests: list[list[BaseMessage]], summary_text: str, *, after_call_index: int = 0) -> bool:
    '执行 _summary_visible_in_requests 的明确职责，并返回与调用约定一致的结果'
    snippet = summary_text[:80]
    if not snippet:
        return False
    for messages in requests[after_call_index:]:
        text = "\n".join(_message_text(message) for message in messages)
        if "Conversation summary so far" in text and snippet in text:
            return True
    return False


def test_live_summary_preserves_delegations_and_prevents_repeat(live_client):
    '验证 live、summary、preserves、delegations、and、prevents、repeat 场景下的预期行为、边界条件与结果'
    client, recorder = live_client
    thread_id = f"live-ledger-{uuid.uuid4().hex[:8]}"

    first_events = _stream_events(
        client,
        thread_id,
        """
This is a live delegation-ledger validation.

In your FIRST assistant action, call the `task` tool exactly twice in parallel.
Use subagent_type="general-purpose" for both calls.
Do not answer directly until both task results return.

Task 1:
- description: ledger alpha fact
- prompt: Return exactly one short sentence containing ALPHA_LEDGER_RESULT and no tool use.

Task 2:
- description: ledger beta fact
- prompt: Return exactly one short sentence containing BETA_LEDGER_RESULT and no tool use.

After both task results return, answer in at most three sentences and include both result markers.
""",
    )
    first_task_calls = _task_calls(first_events)
    task_ids = {str(call["id"]) for call in first_task_calls if call.get("id")}
    assert len(task_ids) >= 2, f"expected at least two real task calls, got {first_task_calls}"

    values = _state_values(client, thread_id)
    ledger = _ledger_entries(values)
    descriptions = {entry["description"] for entry in ledger}
    assert "ledger alpha fact" in descriptions
    assert "ledger beta fact" in descriptions

    filler_count = 0
    while filler_count < 8:
        values = _state_values(client, thread_id)
        if _summary_text(values) and not _task_ids_in_state(values, task_ids):
            break
        filler_count += 1
        _stream_events(
            client,
            thread_id,
            f"Compression filler turn {filler_count}. Reply with exactly: LEDGER_FILLER_{filler_count}. Do not use tools.",
        )

    values = _state_values(client, thread_id)
    compressed_summary = _summary_text(values)
    assert compressed_summary, "expected real summarization to write summary_text"
    assert not _has_summary_message(values), "summary should not be stored as a message"
    assert not _task_ids_in_state(values, task_ids), "expected original task messages to be compacted out of state"
    assert {"ledger alpha fact", "ledger beta fact"}.issubset({entry["description"] for entry in _ledger_entries(values)})
    assert _ledger_visible_in_requests(recorder.injected_calls), "expected ledger block in at least one real model request after compression"
    assert _summary_visible_in_requests(recorder.injected_calls, compressed_summary), "expected summary_text in at least one real model request after compression"

    injections_before_followup = len(recorder.injected_calls)
    followup_events = _stream_events(
        client,
        thread_id,
        """
I lost the earlier context. Finish the original ledger alpha fact and ledger beta fact work now.
Use already delegated results if they exist; do not repeat an identical delegated task.
""",
    )

    repeated = [call for call in _task_calls(followup_events) if (call.get("args") or {}).get("description") in {"ledger alpha fact", "ledger beta fact"}]
    assert repeated == []
    assert _ledger_visible_in_requests(recorder.injected_calls, after_call_index=injections_before_followup)


def test_skill_context_survives_compaction_live(live_client):
    '验证 skill、context、survives、compaction、live 场景下的预期行为、边界条件与结果'
    client, recorder = live_client
    thread_id = f"live-skill-{uuid.uuid4().hex[:8]}"

    events = _stream_events(
        client,
        thread_id,
        """
Read exactly this file now with the read_file tool: /mnt/skills/public/data-analysis/SKILL.md
After the tool result returns, briefly say you are ready. Do not use any other tool.
""",
    )
    assert events

    state_after_load = _state_values(client, thread_id)
    loaded = _skill_paths_in_state(state_after_load)
    captured_path = "/mnt/skills/public/data-analysis/SKILL.md"
    assert captured_path in loaded, f"no skill captured into channel: {loaded}"
    skill_context = list(state_after_load.get("skill_context") or [])
    assert "Use this skill when the user uploads Excel" in repr(skill_context)
    assert "Data Analysis Skill" not in repr(skill_context)

    for prompt in ("Give me one short tip.", "Give me one more short tip.", "And one final short tip."):
        _stream_events(client, thread_id, prompt)

    final_state = _state_values(client, thread_id)
    assert captured_path in _skill_paths_in_state(final_state)
    assert any(snap["has_summary_text"] for snap in recorder.before_model_states), "summarization never ran"
    assert recorder.injected_calls, "durable context never injected"
    last_injected = recorder.injected_calls[-1]
    active = next(
        (message for message in last_injected if isinstance(message, HumanMessage) and message.additional_kwargs.get("durable_context_data") and "Active skills" in _message_text(message)),
        None,
    )
    assert active is not None, "skill context not present in final injected request"
    active_text = _message_text(active)
    assert "re-read" in active_text.lower()
    assert captured_path in active_text
    assert "Use this skill when the user uploads Excel" in active_text
    assert "Data Analysis Skill" not in active_text
