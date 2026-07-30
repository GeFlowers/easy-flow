"定义 test_client_langfuse_metadata 模块提供的职责与可复用接口。\n\nTests for DeerFlowClient's graph-root tracing wiring.\n\nRegression coverage for the Copilot review on PR #2944: when the title\nand summarization middlewares request ``attach_tracing=False`` we must\nmake sure ``DeerFlowClient`` injects the tracing callbacks at the graph\ninvocation root instead, otherwise those middlewares produce untraced\nLLM calls.\n"

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deerflow.client import DeerFlowClient
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, request_trace_context


class _FakeAgent:
    '封装 _FakeAgent 的状态、协作关系与公开操作。\n\nCapture the ``config`` handed to ``agent.stream``.'

    def __init__(self) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        self.captured_config: dict | None = None
        self.checkpointer = None
        self.store = None

    def stream(self, state, *, config, context, stream_mode):
        '持续产出流式结果并传递终止状态，并遵守 stream 所表达的接口约束'
        self.captured_config = config
        return iter(())  # empty stream


@pytest.fixture(autouse=True)
def _clear_langfuse_env(monkeypatch):
    '执行 _clear_langfuse_env 的明确职责，并返回与调用约定一致的结果'
    from deerflow.config.tracing_config import reset_tracing_config

    for name in ("LANGFUSE_TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    yield
    reset_tracing_config()


def _stub_agent_creation(monkeypatch, fake_agent: _FakeAgent) -> dict[str, Any]:
    '执行 _stub_agent_creation 的明确职责，并返回与调用约定一致的结果。\n\nShort-circuit the heavy parts of ``_ensure_agent`` so we can drive\n    ``stream()`` against a fake graph without touching real models, tools\n    or middleware factories.\n    '
    captured: dict[str, Any] = {}

    def _stub_ensure_agent(self, config):
        '执行 _stub_ensure_agent 的明确职责，并返回与调用约定一致的结果'
        captured["config"] = config
        self._agent = fake_agent
        self._agent_config_key = ("stub",)

    monkeypatch.setattr(DeerFlowClient, "_ensure_agent", _stub_ensure_agent)
    return captured


def _make_client(_monkeypatch, *, enhance_enabled: bool = True) -> DeerFlowClient:
    '执行 _make_client 的明确职责，并返回与调用约定一致的结果。\n\nBuild a client without going through ``__init__`` so we never load\n    config.yaml or perform any other side-effectful startup work.\n\n    ``enhance_enabled`` seeds the ``logging.enhance.enabled`` flag that\n    :func:`DeerFlowClient.stream` consults to gate request-trace binding\n    (mirrors the Gateway ``TraceMiddleware`` startup snapshot).\n    '
    fake_app_config = SimpleNamespace(
        models=[SimpleNamespace(name="stub-model")],
        logging=SimpleNamespace(enhance=SimpleNamespace(enabled=enhance_enabled)),
    )
    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = fake_app_config
    client._extensions_config = None
    client._model_name = "stub-model"
    client._thinking_enabled = False
    client._plan_mode = False
    client._subagent_enabled = False
    client._agent_name = None
    client._available_skills = None
    client._middlewares = None
    client._checkpointer = None
    client._agent = None
    client._agent_config_key = None
    client._environment = None
    return client


def test_stream_injects_langfuse_metadata_when_enabled(monkeypatch):
    '验证 stream、injects、langfuse、metadata、when、enabled 场景下的预期行为、边界条件与结果'
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    class _SentinelHandler:
        '封装 _SentinelHandler 的状态、协作关系与公开操作'
        pass

    sentinel = _SentinelHandler()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [sentinel])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    list(client.stream("hi", thread_id="thread-client-1"))

    config = captured["config"]
    metadata = config.get("metadata") or {}
    assert metadata.get("langfuse_session_id") == "thread-client-1"
    assert metadata.get("langfuse_trace_name") == "lead-agent"
    assert metadata.get(DEERFLOW_TRACE_METADATA_KEY)
    # 默认无身份验证上下文回退到“默认”用户。
    assert metadata.get("langfuse_user_id") in {"default", "test-user-autouse"}
    callbacks = config.get("callbacks") or []
    assert sentinel in callbacks


def test_stream_is_inert_when_langfuse_disabled(monkeypatch):
    '验证 stream、is、inert、when、langfuse、disabled 场景下的预期行为、边界条件与结果'
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    list(client.stream("hi", thread_id="thread-client-2"))

    config = captured["config"]
    assert "callbacks" not in config or not config["callbacks"]
    metadata = config.get("metadata") or {}
    assert "langfuse_session_id" not in metadata
    assert "langfuse_user_id" not in metadata


def test_stream_preserves_caller_metadata_overrides(monkeypatch):
    '验证 stream、preserves、caller、metadata、overrides 场景下的预期行为、边界条件与结果'
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    # Drive stream with a pre-populated metadata so the worker-equivalent
    # 使用预先填充的元数据驱动流，以便工作人员等效
    original_get_config = DeerFlowClient._get_runnable_config

    def patched_get_runnable_config(self, thread_id, **overrides):
        '执行 patched_get_runnable_config 的明确职责，并返回与调用约定一致的结果'
        cfg = original_get_config(self, thread_id, **overrides)
        cfg["metadata"] = {
            DEERFLOW_TRACE_METADATA_KEY: "explicit-client-trace",
            "langfuse_session_id": "explicit-session-override",
            "langfuse_user_id": "explicit-user",
        }
        return cfg

    monkeypatch.setattr(DeerFlowClient, "_get_runnable_config", patched_get_runnable_config)
    with request_trace_context("client-trace-3"):
        list(client.stream("hi", thread_id="thread-client-3"))

    metadata = captured["config"].get("metadata") or {}
    assert metadata["langfuse_session_id"] == "explicit-session-override"
    assert metadata["langfuse_user_id"] == "explicit-user"
    assert metadata[DEERFLOW_TRACE_METADATA_KEY] == "explicit-client-trace"
    # ``trace_name`` 未由调用者提供，因此工作人员仍会填充它。
    assert metadata["langfuse_trace_name"] == "lead-agent"


def test_stream_omits_deerflow_trace_id_when_enhance_disabled(monkeypatch):
    '验证 stream、omits、deerflow、trace、id、when、enhance、disabled 场景下的预期行为、边界条件与结果。\n\nWith ``logging.enhance.enabled=false`` the embedded client must not\n    forge a fresh request trace id. Otherwise embedded / TUI callers on the\n    default config would silently gain a new indexed ``deerflow_trace_id``\n    key on every Langfuse trace they emit — the exact schema change the\n    enhancement flag exists to opt into.\n    '
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch, enhance_enabled=False)

    list(client.stream("hi", thread_id="thread-client-disabled"))

    metadata = captured["config"].get("metadata") or {}
    # Session / user still bind — those are Langfuse-native trace attributes
    # 会话/用户仍然绑定 - 这些是 Langfuse 原生跟踪属性
    assert metadata.get("langfuse_session_id") == "thread-client-disabled"
    assert metadata.get("langfuse_trace_name") == "lead-agent"
    # 门控密钥不存在于元数据中。
    assert DEERFLOW_TRACE_METADATA_KEY not in metadata


def test_stream_respects_caller_bound_trace_when_enhance_disabled(monkeypatch):
    '验证 stream、respects、caller、bound、trace、when、enhance、disabled 场景下的预期行为、边界条件与结果。\n\nEven with the enhancement disabled, a caller that explicitly binds\n    :func:`request_trace_context` has opted into propagation. The embedded\n    client must not swallow that id — the flag only gates *implicit*\n    per-turn id creation, not caller-supplied context.'
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch, enhance_enabled=False)

    with request_trace_context("caller-opt-in"):
        list(client.stream("hi", thread_id="thread-client-opt-in"))

    metadata = captured["config"].get("metadata") or {}
    assert metadata.get(DEERFLOW_TRACE_METADATA_KEY) == "caller-opt-in"


def test_stream_does_not_leak_trace_id_to_caller_context_between_yields(monkeypatch):
    "验证 stream、does、not、leak、trace、id、to、caller、context、between、yields 场景下的预期行为、边界条件与结果。\n\nEnable branch must bind the trace id only around each ``next()`` step\n    and reset it before yielding. ``stream()`` is a sync generator, which\n    shares the caller's context, so a ``with ensure_trace_context(): yield\n    from ...`` would leak the stream's id into the caller's context between\n    iterations — any caller code that read ``get_current_trace_id()`` (a\n    log filter, a follow-up ``inject_langfuse_metadata`` for unrelated\n    work) would pick up this stream's id instead of the caller's own trace\n    state. Per-step set/reset keeps the caller's context clean at every\n    yield boundary.\n    "
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    class _TwoEventAgent:
        '封装 _TwoEventAgent 的状态、协作关系与公开操作'
        def __init__(self) -> None:
            '实现 __init__ 协议方法，保持对象交互语义一致'
            self.checkpointer = None
            self.store = None

        def stream(self, state, *, config, context, stream_mode):
            '持续产出流式结果并传递终止状态，并遵守 stream 所表达的接口约束'
            yield ("values", {"messages": [], "artifacts": []})
            yield ("values", {"messages": [], "artifacts": []})

    _stub_agent_creation(monkeypatch, _TwoEventAgent())
    client = _make_client(monkeypatch, enhance_enabled=True)

    from deerflow.trace_context import get_current_trace_id

    # 调用者的上下文以没有跟踪 id 绑定的方式开始。
    assert get_current_trace_id() is None

    observations: list[str | None] = []
    for _event in client.stream("hi", thread_id="thread-no-leak"):
        observations.append(get_current_trace_id())

    # Between every yield the caller sees their own (unbound) trace state,
    # 在每个yield之间，调用者都会看到自己的（未绑定的）跟踪状态，
    assert observations, "expected at least one event"
    assert all(obs is None for obs in observations), observations
    # 迭代完成后，仍然没有泄漏。
    assert get_current_trace_id() is None


def test_stream_abandoned_generator_close_does_not_raise_cross_context(monkeypatch):
    "验证 stream、abandoned、generator、close、does、not、raise、cross、context 场景下的预期行为、边界条件与结果。\n\nClosing a partially-iterated stream from a different ``Context`` must\n    not raise ``ValueError: <Token> was created in a different Context``.\n    Sync generators share the caller's context on set/reset; a ``with``\n    block spanning ``yield from`` would create a Token in the caller's\n    Context on the first ``next()`` and only release it via ``__exit__`` on\n    ``close()`` — GC-driven finalization on a different asyncio Task (or,\n    as simulated here, inside a ``copy_context()`` fork) would then blow up\n    with a cross-context reset. Per-step set/reset never leaves a Token\n    outstanding across yield boundaries.\n    "
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    class _InfiniteAgent:
        '封装 _InfiniteAgent 的状态、协作关系与公开操作'
        def __init__(self) -> None:
            '实现 __init__ 协议方法，保持对象交互语义一致'
            self.checkpointer = None
            self.store = None

        def stream(self, state, *, config, context, stream_mode):
            '持续产出流式结果并传递终止状态，并遵守 stream 所表达的接口约束'
            while True:
                yield ("values", {"messages": [], "artifacts": []})

    _stub_agent_creation(monkeypatch, _InfiniteAgent())
    client = _make_client(monkeypatch, enhance_enabled=True)

    gen = client.stream("hi", thread_id="thread-cross-ctx")
    # Pull one event in the current Context — a buggy implementation would
    # 在当前上下文中拉取一个事件——一个有缺陷的实现会
    next(gen)

    import contextvars

    isolated_ctx = contextvars.copy_context()
    # Invoke ``gen.close()`` inside a distinct Context; the outer Context's
    # Tokens (if any) cannot be reset from here. Reaching this line without
    # 在不同的上下文中调用``gen.close()``；外部上下文的
    isolated_ctx.run(gen.close)
