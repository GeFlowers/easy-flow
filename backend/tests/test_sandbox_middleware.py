'未说明'
from __future__ import annotations

import asyncio
from typing import get_type_hints

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from deerflow.agents.thread_state import ThreadState
from deerflow.sandbox.middleware import SandboxMiddleware, SandboxMiddlewareState
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider, reset_sandbox_provider, set_sandbox_provider
from deerflow.sandbox.search import GrepMatch
from deerflow.sandbox.tools import ls_tool


class _SyncProvider(SandboxProvider):
    '未说明'
    def __init__(self) -> None:
        '未说明'
        self.thread_ids: list[str | None] = []
        self.user_ids: list[str | None] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        '未说明'
        self.thread_ids.append(thread_id)
        self.user_ids.append(user_id)
        return "sync-sandbox"

    def get(self, sandbox_id: str) -> Sandbox | None:
        """处理获取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None

    def release(self, sandbox_id: str) -> None:
        '未说明'
        return None


class _SandboxStub(Sandbox):
    '未说明'
    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        '未说明'
        del env, timeout
        return "OK"

    def read_file(self, path: str) -> str:
        """处理读取 文件相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return "content"

    def download_file(self, path: str) -> bytes:
        """处理文件相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return b"content"

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        '未说明'
        return ["/mnt/user-data/workspace/file.txt"]

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """处理写入 文件相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        '未说明'
        return [], False

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        '未说明'
        return [], False

    def update_file(self, path: str, content: bytes) -> None:
        """处理文件相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None


class _AsyncOnlyProvider(SandboxProvider):
    '未说明'
    def __init__(self) -> None:
        '未说明'
        self.thread_ids: list[str | None] = []
        self.user_ids: list[str | None] = []
        self.released_ids: list[str] = []
        self.sandbox = _SandboxStub("async-sandbox")

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        '未说明'
        del user_id
        raise AssertionError("async middleware should not call sync acquire")

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        '未说明'
        self.thread_ids.append(thread_id)
        self.user_ids.append(user_id)
        return "async-sandbox"

    def get(self, sandbox_id: str) -> Sandbox | None:
        """处理获取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        if sandbox_id == "async-sandbox":
            return self.sandbox
        return None

    def release(self, sandbox_id: str) -> None:
        '未说明'
        self.released_ids.append(sandbox_id)
        return None


def test_sandbox_middleware_state_matches_thread_state_sandbox_field() -> None:
    '未说明'
    middleware_hints = get_type_hints(SandboxMiddlewareState, include_extras=True)
    thread_hints = get_type_hints(ThreadState, include_extras=True)

    assert middleware_hints["sandbox"] == thread_hints["sandbox"]


@pytest.mark.anyio
async def test_provider_default_acquire_async_offloads_sync_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    '未说明'
    provider = _SyncProvider()
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        '未说明'
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    sandbox_id = await provider.acquire_async("thread-1")

    assert sandbox_id == "sync-sandbox"
    assert provider.thread_ids == ["thread-1"]
    assert provider.user_ids == [None]
    assert calls == [(provider.acquire, ("thread-1",), {"user_id": None})]


@pytest.mark.anyio
async def test_abefore_agent_uses_async_provider_acquire() -> None:
    '未说明'
    provider = _AsyncOnlyProvider()
    set_sandbox_provider(provider)
    try:
        middleware = SandboxMiddleware(lazy_init=False)

        result = await middleware.abefore_agent({}, Runtime(context={"thread_id": "thread-2", "user_id": "owner-2"}))
    finally:
        reset_sandbox_provider()

    assert result == {"sandbox": {"sandbox_id": "async-sandbox"}}
    assert provider.thread_ids == ["thread-2"]
    assert provider.user_ids == ["owner-2"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("middleware", "state", "runtime"),
    [
        (SandboxMiddleware(lazy_init=True), {}, Runtime(context={"thread_id": "thread-lazy"})),
        (SandboxMiddleware(lazy_init=False), {}, Runtime(context={})),
        (SandboxMiddleware(lazy_init=False), {"sandbox": {"sandbox_id": "existing"}}, Runtime(context={"thread_id": "thread-existing"})),
    ],
)
async def test_abefore_agent_delegates_to_super_when_not_acquiring(
    monkeypatch: pytest.MonkeyPatch,
    middleware: SandboxMiddleware,
    state: dict,
    runtime: Runtime,
) -> None:
    '未说明'
    calls: list[tuple[dict, Runtime]] = []

    async def fake_super_abefore_agent(self, state_arg, runtime_arg):
        '未说明'
        calls.append((state_arg, runtime_arg))
        return {"delegated": True}

    monkeypatch.setattr(AgentMiddleware, "abefore_agent", fake_super_abefore_agent)

    result = await middleware.abefore_agent(state, runtime)

    assert result == {"delegated": True}
    assert calls == [(state, runtime)]


@pytest.mark.anyio
async def test_default_lazy_tool_acquisition_uses_async_provider() -> None:
    '未说明'
    provider = _AsyncOnlyProvider()
    set_sandbox_provider(provider)
    try:
        runtime = ToolRuntime(
            state={},
            context={"thread_id": "thread-lazy", "user_id": "owner-lazy"},
            config={"configurable": {}},
            stream_writer=lambda _: None,
            tools=[],
            tool_call_id="call-1",
            store=None,
        )

        result = await ls_tool.ainvoke({"runtime": runtime, "description": "list workspace", "path": "/mnt/user-data/workspace"})
    finally:
        reset_sandbox_provider()

    assert result == "/mnt/user-data/workspace/file.txt"
    assert provider.thread_ids == ["thread-lazy"]
    assert provider.user_ids == ["owner-lazy"]
    assert runtime.state["sandbox"] == {"sandbox_id": "async-sandbox"}
    assert runtime.context["sandbox_id"] == "async-sandbox"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("state", "runtime", "expected_sandbox_id"),
    [
        ({"sandbox": {"sandbox_id": "state-sandbox"}}, Runtime(context={}), "state-sandbox"),
        ({}, Runtime(context={"sandbox_id": "context-sandbox"}), "context-sandbox"),
    ],
)
async def test_aafter_agent_releases_sandbox_off_thread(
    monkeypatch: pytest.MonkeyPatch,
    state: dict,
    runtime: Runtime,
    expected_sandbox_id: str,
) -> None:
    '未说明'
    provider = _AsyncOnlyProvider()
    to_thread_calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, /, *args):
        '未说明'
        to_thread_calls.append((func, args))
        return func(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    set_sandbox_provider(provider)
    try:
        result = await SandboxMiddleware().aafter_agent(state, runtime)
    finally:
        reset_sandbox_provider()

    assert result is None
    assert provider.released_ids == [expected_sandbox_id]
    assert to_thread_calls == [(provider.release, (expected_sandbox_id,))]


@pytest.mark.anyio
async def test_aafter_agent_delegates_to_super_when_no_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    '未说明'
    calls: list[tuple[dict, Runtime]] = []

    async def fake_super_aafter_agent(self, state_arg, runtime_arg):
        '未说明'
        calls.append((state_arg, runtime_arg))
        return {"delegated": True}

    monkeypatch.setattr(AgentMiddleware, "aafter_agent", fake_super_aafter_agent)

    state = {}
    runtime = Runtime(context={})
    result = await SandboxMiddleware().aafter_agent(state, runtime)

    assert result == {"delegated": True}
    assert calls == [(state, runtime)]


# ---------------------------------------------------------------------------
# wrap_tool_call / awrap_tool_call: persistent sandbox state via Command
# ---------------------------------------------------------------------------


def _make_tool_call_request(state: dict) -> ToolCallRequest:
    '未说明'
    runtime = ToolRuntime(
        state=state,
        context={},
        config={"configurable": {}},
        stream_writer=lambda _: None,
        tools=[],
        tool_call_id="call-1",
        store=None,
    )
    return ToolCallRequest(
        tool_call={"id": "call-1", "name": "bash", "args": {}},
        tool=None,
        state=state,
        runtime=runtime,
    )


def test_wrap_tool_call_emits_command_when_lazy_init_happens() -> None:
    '未说明'
    middleware = SandboxMiddleware()
    state: dict = {}
    request = _make_tool_call_request(state)

    def handler(req: ToolCallRequest) -> ToolMessage:
        # Simulate ensure_sandbox_initialized() mutating runtime.state in-place.
        '未说明'
        req.runtime.state["sandbox"] = {"sandbox_id": "new-sandbox"}
        return ToolMessage(content="ok", tool_call_id="call-1", name="bash")

    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, Command)
    assert isinstance(result.update, dict)
    assert result.update["sandbox"] == {"sandbox_id": "new-sandbox"}
    messages = result.update["messages"]
    assert len(messages) == 1
    assert messages[0].content == "ok"
    assert messages[0].tool_call_id == "call-1"


def test_wrap_tool_call_passthrough_when_sandbox_already_in_state() -> None:
    '未说明'
    middleware = SandboxMiddleware()
    state: dict = {"sandbox": {"sandbox_id": "existing"}}
    request = _make_tool_call_request(state)
    original = ToolMessage(content="ok", tool_call_id="call-1", name="bash")

    def handler(req: ToolCallRequest) -> ToolMessage:
        '未说明'
        return original

    result = middleware.wrap_tool_call(request, handler)

    assert result is original


def test_wrap_tool_call_passthrough_when_handler_did_not_initialize_sandbox() -> None:
    '未说明'
    middleware = SandboxMiddleware()
    state: dict = {}
    request = _make_tool_call_request(state)
    original = ToolMessage(content="ok", tool_call_id="call-1", name="bash")

    def handler(req: ToolCallRequest) -> ToolMessage:
        '未说明'
        return original

    result = middleware.wrap_tool_call(request, handler)

    assert result is original


def test_wrap_tool_call_merges_with_existing_command_update() -> None:
    '未说明'
    middleware = SandboxMiddleware()
    state: dict = {}
    request = _make_tool_call_request(state)
    tool_msg = ToolMessage(content="ok", tool_call_id="call-1", name="bash")

    def handler(req: ToolCallRequest) -> Command:
        '未说明'
        req.runtime.state["sandbox"] = {"sandbox_id": "new-sandbox"}
        return Command(
            update={
                "messages": [tool_msg],
                "viewed_images": {"a.png": {"mime_type": "image/png", "size": 1, "actual_path": "/tmp/a.png"}},
            },
            goto="next-node",
        )

    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, Command)
    assert result.goto == "next-node"
    assert isinstance(result.update, dict)
    assert result.update["messages"] == [tool_msg]
    assert result.update["viewed_images"] == {"a.png": {"mime_type": "image/png", "size": 1, "actual_path": "/tmp/a.png"}}
    assert result.update["sandbox"] == {"sandbox_id": "new-sandbox"}


def test_wrap_tool_call_does_not_override_non_dict_update() -> None:
    '未说明'
    middleware = SandboxMiddleware()
    state: dict = {}
    request = _make_tool_call_request(state)
    cmd = Command(update=[("messages", [ToolMessage(content="x", tool_call_id="c", name="bash")])])

    def handler(req: ToolCallRequest) -> Command:
        '未说明'
        req.runtime.state["sandbox"] = {"sandbox_id": "new-sandbox"}
        return cmd

    result = middleware.wrap_tool_call(request, handler)

    # Non-dict update is left untouched to avoid silent data loss.
    assert result is cmd


@pytest.mark.anyio
async def test_awrap_tool_call_emits_command_when_lazy_init_happens() -> None:
    '未说明'
    middleware = SandboxMiddleware()
    state: dict = {}
    request = _make_tool_call_request(state)

    async def handler(req: ToolCallRequest) -> ToolMessage:
        '未说明'
        req.runtime.state["sandbox"] = {"sandbox_id": "async-new"}
        return ToolMessage(content="ok", tool_call_id="call-1", name="bash")

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, Command)
    assert isinstance(result.update, dict)
    assert result.update["sandbox"] == {"sandbox_id": "async-new"}
    messages = result.update["messages"]
    assert len(messages) == 1
    assert messages[0].content == "ok"


@pytest.mark.anyio
async def test_awrap_tool_call_passthrough_when_sandbox_already_in_state() -> None:
    '未说明'
    middleware = SandboxMiddleware()
    state: dict = {"sandbox": {"sandbox_id": "existing"}}
    request = _make_tool_call_request(state)
    original = ToolMessage(content="ok", tool_call_id="call-1", name="bash")

    async def handler(req: ToolCallRequest) -> ToolMessage:
        '未说明'
        return original

    result = await middleware.awrap_tool_call(request, handler)

    assert result is original


def test_wrap_tool_call_preserves_existing_command_fields_when_merging() -> None:
    '未说明'
    middleware = SandboxMiddleware()
    state: dict = {}
    request = _make_tool_call_request(state)

    def handler(req: ToolCallRequest) -> Command:
        '未说明'
        req.runtime.state["sandbox"] = {"sandbox_id": "sbx-merge"}
        return Command(
            update={"existing_key": "existing_value"},
            graph="parent",
            goto="next_node",
            resume="resume-token",
        )

    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, Command)
    assert result.update == {
        "existing_key": "existing_value",
        "sandbox": {"sandbox_id": "sbx-merge"},
    }
    # Critical: other Command fields must NOT be dropped by the merge.
    assert result.graph == "parent"
    assert result.goto == "next_node"
    assert result.resume == "resume-token"
