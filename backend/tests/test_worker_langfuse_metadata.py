'未说明'

from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, request_trace_context


class _FakeAgent:
    '未说明'

    def __init__(self) -> None:
        '未说明'
        self.captured_config: dict | None = None
        self.metadata: dict = {}
        # Worker may assign these attributes; need them to exist.
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes: list[str] = []
        self.interrupt_after_nodes: list[str] = []

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        '未说明'
        self.captured_config = config
        # Empty async generator — no chunks produced.
        return
        yield  # pragma: no cover (makes this an async generator)


class _FakeRunManager:
    '未说明'
    async def wait_for_prior_finalizing(self, *_args, **_kwargs) -> None:
        '未说明'
        return None

    async def has_later_run(self, *_args, **_kwargs) -> bool:
        """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return False

    async def has_later_started_run(self, *_args, **_kwargs) -> bool:
        """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return False

    async def set_status(self, *_args, **_kwargs) -> None:
        '未说明'
        return None

    async def update_model_name(self, *_args, **_kwargs) -> None:
        """处理模型相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None

    async def update_run_completion(self, *_args, **_kwargs) -> None:
        """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None


class _FakeBridge:
    '未说明'
    def __init__(self) -> None:
        '未说明'
        self.events: list[tuple[str, object]] = []

    async def publish(self, _run_id, event, payload) -> None:
        '未说明'
        self.events.append((event, payload))

    async def publish_end(self, _run_id) -> None:
        '未说明'
        self.events.append(("end", None))

    async def cleanup(self, _run_id, *, delay: int = 0) -> None:
        '未说明'
        return None


@pytest.fixture(autouse=True)
def _clear_tracing_env(monkeypatch):
    '未说明'
    from deerflow.config.tracing_config import reset_tracing_config

    for name in ("LANGFUSE_TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    yield
    reset_tracing_config()


@pytest.mark.asyncio
async def test_run_agent_injects_langfuse_metadata(monkeypatch):
    '未说明'
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    fake_agent = _FakeAgent()

    def agent_factory(config):
        '未说明'
        return fake_agent

    record = RunRecord(
        run_id="run-1",
        thread_id="thread-xyz",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        model_name="gpt-4o",
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    with request_trace_context("gateway-trace-1"):
        await run_agent(
            _FakeBridge(),
            _FakeRunManager(),
            record,
            ctx=ctx,
            agent_factory=agent_factory,
            graph_input={"messages": []},
            config={"configurable": {"thread_id": "thread-xyz"}},
        )

    assert fake_agent.captured_config is not None, "astream was not invoked"
    metadata = fake_agent.captured_config.get("metadata") or {}
    assert metadata.get("langfuse_session_id") == "thread-xyz"
    # conftest.py autouse fixture injects ``test-user-autouse`` into the
    # contextvar — the worker should read it via ``get_effective_user_id``.
    user_id = metadata.get("langfuse_user_id")
    assert user_id == "test-user-autouse", f"expected test-user-autouse, got {user_id}"
    assert metadata.get("langfuse_trace_name") == "lead-agent"
    assert metadata.get(DEERFLOW_TRACE_METADATA_KEY) == "gateway-trace-1"
    assert fake_agent.captured_config.get("context", {}).get(DEERFLOW_TRACE_METADATA_KEY) == "gateway-trace-1"
    tags = metadata.get("langfuse_tags") or []
    assert "model:gpt-4o" in tags


@pytest.mark.asyncio
async def test_run_agent_uses_context_user_id_over_contextvar(monkeypatch):
    '未说明'
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    fake_agent = _FakeAgent()

    def agent_factory(config):
        '未说明'
        return fake_agent

    record = RunRecord(
        run_id="run-ctx-user",
        thread_id="thread-ctx",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=ctx,
        agent_factory=agent_factory,
        graph_input={"messages": []},
        config={
            "configurable": {"thread_id": "thread-ctx"},
            "context": {"user_id": "real-end-user"},
        },
    )

    metadata = fake_agent.captured_config.get("metadata") or {}
    # context.user_id wins over the contextvar's ``test-user-autouse``.
    assert metadata.get("langfuse_user_id") == "real-end-user"


@pytest.mark.asyncio
async def test_run_agent_falls_back_to_default_user_when_unset(monkeypatch):
    '未说明'
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.runtime import user_context as user_context_module
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    reset_tracing_config()
    monkeypatch.setattr(user_context_module, "get_effective_user_id", lambda: DEFAULT_USER_ID)

    fake_agent = _FakeAgent()

    def agent_factory(config):
        '未说明'
        return fake_agent

    record = RunRecord(
        run_id="run-fallback",
        thread_id="thread-fb",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=ctx,
        agent_factory=agent_factory,
        graph_input={"messages": []},
        config={"configurable": {"thread_id": "thread-fb"}},
    )

    metadata = fake_agent.captured_config.get("metadata") or {}
    assert metadata.get("langfuse_user_id") == "default"


@pytest.mark.asyncio
async def test_run_agent_preserves_caller_metadata_overrides(monkeypatch):
    '未说明'
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    fake_agent = _FakeAgent()

    def agent_factory(config):
        '未说明'
        return fake_agent

    record = RunRecord(
        run_id="run-2",
        thread_id="thread-default",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=ctx,
        agent_factory=agent_factory,
        graph_input={"messages": []},
        config={
            "configurable": {"thread_id": "thread-default"},
            "metadata": {
                DEERFLOW_TRACE_METADATA_KEY: "explicit-deerflow-trace",
                "langfuse_session_id": "custom-session-id",
                "langfuse_user_id": "explicit-user",
            },
        },
    )

    metadata = fake_agent.captured_config.get("metadata") or {}
    # Caller-supplied keys win.
    assert metadata["langfuse_session_id"] == "custom-session-id"
    assert metadata["langfuse_user_id"] == "explicit-user"
    assert metadata[DEERFLOW_TRACE_METADATA_KEY] == "explicit-deerflow-trace"
    assert fake_agent.captured_config.get("context", {}).get(DEERFLOW_TRACE_METADATA_KEY) == "explicit-deerflow-trace"
    # Worker still fills in keys that the caller didn't set.
    assert metadata["langfuse_trace_name"] == "lead-agent"


@pytest.mark.asyncio
async def test_run_agent_skips_metadata_when_langfuse_disabled(monkeypatch):
    '未说明'
    fake_agent = _FakeAgent()

    def agent_factory(config):
        '未说明'
        return fake_agent

    record = RunRecord(
        run_id="run-3",
        thread_id="thread-noop",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=ctx,
        agent_factory=agent_factory,
        graph_input={"messages": []},
        config={"configurable": {"thread_id": "thread-noop"}},
    )

    metadata = fake_agent.captured_config.get("metadata") or {}
    assert "langfuse_session_id" not in metadata
    assert "langfuse_user_id" not in metadata
    assert "langfuse_trace_name" not in metadata
