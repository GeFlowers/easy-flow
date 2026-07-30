"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp

from deerflow.agents.middlewares.llm_error_handling_middleware import (
    LLMErrorHandlingMiddleware,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


def _make_app_config() -> AppConfig:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return AppConfig(sandbox=SandboxConfig(use="test"))


class FakeError(Exception):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        body: dict | None = None,
    ) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.body = body
        self.response = SimpleNamespace(status_code=status_code, headers=headers or {}) if status_code is not None or headers else None


def _build_middleware(**attrs: int) -> LLMErrorHandlingMiddleware:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    middleware = LLMErrorHandlingMiddleware(app_config=_make_app_config())
    for key, value in attrs.items():
        setattr(middleware, key, value)
    return middleware


def test_async_model_call_retries_busy_provider_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=3, retry_base_delay_ms=25, retry_cap_delay_ms=25)
    attempts = 0
    waits: list[float] = []
    events: list[dict] = []

    async def fake_sleep(delay: float) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        waits.append(delay)

    def fake_writer():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return events.append

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise FakeError("当前服务集群负载较高，请稍后重试，感谢您的耐心等待。 (2064)")
        return AIMessage(content="ok")

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "langgraph.config.get_stream_writer",
        fake_writer,
    )

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert attempts == 3
    assert waits == [0.025, 0.025]
    assert [event["type"] for event in events] == ["llm_retry", "llm_retry"]


def test_async_model_call_returns_user_message_for_quota_errors() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=3)

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise FakeError(
            "insufficient_quota: account balance is empty",
            status_code=429,
            code="insufficient_quota",
        )

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert "out of quota" in str(result.content)
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_reason"] == "quota"
    assert result.additional_kwargs["error_type"] == "FakeError"


def test_async_model_call_marks_transient_retry_exhaustion_as_error_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=2, retry_base_delay_ms=25, retry_cap_delay_ms=25)

    async def fake_sleep(_delay: float) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return None

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise FakeError("Connection error.", status_code=503)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert "temporarily unavailable" in str(result.content)
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_reason"] == "transient"
    assert result.additional_kwargs["error_detail"] == "Connection error."


def test_sync_model_call_uses_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=2, retry_base_delay_ms=10, retry_cap_delay_ms=10)
    waits: list[float] = []
    attempts = 0

    def fake_sleep(delay: float) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        waits.append(delay)

    def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FakeError(
                "server busy",
                status_code=503,
                headers={"Retry-After": "2"},
            )
        return AIMessage(content="ok")

    monkeypatch.setattr("time.sleep", fake_sleep)

    result = middleware.wrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert waits == [2.0]


def test_sync_model_call_propagates_graph_bubble_up() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()

    def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise GraphBubbleUp()

    with pytest.raises(GraphBubbleUp):
        middleware.wrap_model_call(SimpleNamespace(), handler)


def test_async_model_call_propagates_graph_bubble_up() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise GraphBubbleUp()

    with pytest.raises(GraphBubbleUp):
        asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))


def test_circuit_half_open_graph_bubble_up_resets_probe() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    middleware._circuit_state = "half_open"
    middleware._circuit_probe_in_flight = False
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise GraphBubbleUp()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    import unittest.mock

    with unittest.mock.patch.object(middleware, "_check_circuit", return_value=False):
        with pytest.raises(GraphBubbleUp):
            middleware.wrap_model_call(SimpleNamespace(), handler)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._circuit_probe_in_flight is False
    assert middleware._circuit_state == "half_open"


@pytest.mark.anyio
async def test_async_circuit_half_open_graph_bubble_up_resets_probe() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    middleware._circuit_state = "half_open"
    middleware._circuit_probe_in_flight = False
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise GraphBubbleUp()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    import unittest.mock

    with unittest.mock.patch.object(middleware, "_check_circuit", return_value=False):
        with pytest.raises(GraphBubbleUp):
            await middleware.awrap_model_call(SimpleNamespace(), handler)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._circuit_probe_in_flight is False
    assert middleware._circuit_state == "half_open"


def test_circuit_half_open_non_retriable_error_resets_probe() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import unittest.mock

    middleware = _build_middleware()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    middleware._circuit_state = "half_open"
    middleware._circuit_probe_in_flight = False
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True

    def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise FakeError("insufficient_quota", status_code=429, code="insufficient_quota")

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    with unittest.mock.patch.object(middleware, "_check_circuit", return_value=False):
        with unittest.mock.patch.object(middleware, "_classify_error", return_value=(False, "quota")):
            result = middleware.wrap_model_call(SimpleNamespace(), handler)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert isinstance(result, AIMessage)
    assert middleware._circuit_state == "half_open"
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._circuit_probe_in_flight is False
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True


@pytest.mark.anyio
async def test_async_circuit_half_open_non_retriable_error_resets_probe() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import unittest.mock

    middleware = _build_middleware()

    middleware._circuit_state = "half_open"
    middleware._circuit_probe_in_flight = False
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise FakeError("insufficient_quota", status_code=429, code="insufficient_quota")

    with unittest.mock.patch.object(middleware, "_check_circuit", return_value=False):
        with unittest.mock.patch.object(middleware, "_classify_error", return_value=(False, "quota")):
            result = await middleware.awrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    assert middleware._circuit_state == "half_open"
    assert middleware._circuit_probe_in_flight is False
    assert middleware._check_circuit() is False
    assert middleware._circuit_probe_in_flight is True


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


def transient_failing_handler(request: Any) -> Any:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    raise FakeError("Server Error", status_code=502)  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


def quota_failing_handler(request: Any) -> Any:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    raise FakeError("Quota exceeded", body={"error": {"code": "insufficient_quota"}})  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


def success_handler(request: Any) -> Any:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return AIMessage(content="Success")


def mock_classify_retriable(exc: BaseException) -> tuple[bool, str]:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return True, "transient"


def mock_classify_non_retriable(exc: BaseException) -> tuple[bool, str]:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return False, "quota"


def test_circuit_breaker_trips_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: waits.append(d))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    current_time = 1000.0
    monkeypatch.setattr("time.time", lambda: current_time)

    middleware = _build_middleware(circuit_failure_threshold=3, circuit_recovery_timeout_sec=10)
    monkeypatch.setattr(middleware, "_classify_error", mock_classify_retriable)

    request: Any = {"messages": []}

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    middleware.wrap_model_call(request, success_handler)
    assert middleware._circuit_failure_count == 0
    assert middleware._check_circuit() is False

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    middleware.wrap_model_call(request, transient_failing_handler)
    assert middleware._circuit_failure_count == 1
    middleware.wrap_model_call(request, transient_failing_handler)
    assert middleware._circuit_failure_count == 2
    middleware.wrap_model_call(request, transient_failing_handler)
    assert middleware._circuit_failure_count == 3
    assert middleware._check_circuit() is True  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    result = middleware.wrap_model_call(request, success_handler)
    assert result.content == middleware._build_circuit_breaker_message()
    assert middleware._circuit_failure_count == 3

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    current_time += 11.0

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._circuit_open_until == current_time - 11.0 + middleware.circuit_recovery_timeout_sec

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    middleware.wrap_model_call(request, transient_failing_handler)
    assert middleware._circuit_failure_count == middleware.circuit_failure_threshold
    assert middleware._circuit_state == "open"  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    current_time += 11.0

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    result = middleware.wrap_model_call(request, success_handler)
    assert result.content == "Success"
    assert middleware._circuit_failure_count == 0  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._check_circuit() is False


def test_circuit_breaker_does_not_trip_on_non_retriable_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: waits.append(d))

    middleware = _build_middleware(circuit_failure_threshold=3)
    monkeypatch.setattr(middleware, "_classify_error", mock_classify_non_retriable)

    request: Any = {"messages": []}

    for _ in range(3):
        middleware.wrap_model_call(request, quota_failing_handler)

    assert middleware._circuit_failure_count == 0
    assert middleware._check_circuit() is False


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class _ReadError(Exception):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""


class _RemoteProtocolError(Exception):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""


_ReadError.__name__ = "ReadError"
_RemoteProtocolError.__name__ = "RemoteProtocolError"


def test_classify_error_read_error_is_retriable() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = _ReadError("Connection dropped mid-stream")
    exc.__class__.__name__ = "ReadError"
    retriable, reason = middleware._classify_error(exc)
    assert retriable is True
    assert reason == "transient"


def test_classify_error_remote_protocol_error_is_retriable() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = _RemoteProtocolError("Server closed connection unexpectedly")
    exc.__class__.__name__ = "RemoteProtocolError"
    retriable, reason = middleware._classify_error(exc)
    assert retriable is True
    assert reason == "transient"


def test_sync_read_error_triggers_retry_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=3, retry_base_delay_ms=10, retry_cap_delay_ms=10)
    attempts = 0
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: waits.append(d))

    def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal attempts
        attempts += 1
        raise _ReadError("Connection dropped mid-stream")

    result = middleware.wrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert "temporarily unavailable" in result.content
    assert "streaming response was interrupted" not in result.content
    assert attempts == 3  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(waits) == 2  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


@pytest.mark.anyio
async def test_async_read_error_triggers_retry_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=3, retry_base_delay_ms=10, retry_cap_delay_ms=10)
    attempts = 0
    waits: list[float] = []

    async def fake_sleep(d: float) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        waits.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal attempts
        attempts += 1
        raise _ReadError("Connection dropped mid-stream")

    result = await middleware.awrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert "temporarily unavailable" in result.content
    assert "streaming response was interrupted" not in result.content
    assert attempts == 3  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(waits) == 2  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


@pytest.mark.anyio
async def test_async_circuit_breaker_trips_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    waits: list[float] = []

    async def fake_sleep(d: float) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        waits.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    current_time = 1000.0
    monkeypatch.setattr("time.time", lambda: current_time)

    middleware = _build_middleware(circuit_failure_threshold=3, circuit_recovery_timeout_sec=10)
    monkeypatch.setattr(middleware, "_classify_error", mock_classify_retriable)

    async def async_failing_handler(request: Any) -> Any:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise FakeError("Server Error", status_code=502)

    request: Any = {"messages": []}

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await middleware.awrap_model_call(request, async_failing_handler)
    assert middleware._circuit_failure_count == 1
    await middleware.awrap_model_call(request, async_failing_handler)
    assert middleware._circuit_failure_count == 2
    await middleware.awrap_model_call(request, async_failing_handler)
    assert middleware._circuit_failure_count == 3
    assert middleware._check_circuit() is True

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    async def async_success_handler(request: Any) -> Any:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return AIMessage(content="Success")

    result = await middleware.awrap_model_call(request, async_success_handler)
    assert result.content == middleware._build_circuit_breaker_message()
    assert middleware._circuit_failure_count == 3  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    current_time += 11.0

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._circuit_open_until == current_time - 11.0 + middleware.circuit_recovery_timeout_sec

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await middleware.awrap_model_call(request, async_failing_handler)
    assert middleware._circuit_failure_count == middleware.circuit_failure_threshold
    assert middleware._circuit_state == "open"  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    current_time += 11.0

    result = await middleware.awrap_model_call(request, async_success_handler)
    assert result.content == "Success"
    assert middleware._circuit_failure_count == 0  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert middleware._check_circuit() is False


class _StreamChunkTimeoutError(Exception):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""


_StreamChunkTimeoutError.__name__ = "StreamChunkTimeoutError"


def test_classify_error_stream_chunk_timeout_is_retriable() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = _StreamChunkTimeoutError("No streaming chunk received for 120.0s (model=mimo-v2.5, chunks_received=58).")
    exc.__class__.__name__ = "StreamChunkTimeoutError"
    retriable, reason = middleware._classify_error(exc)
    assert retriable is True
    assert reason == "transient"


def test_sync_stream_chunk_timeout_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(
        retry_max_attempts=3,
        retry_base_delay_ms=10,
        retry_cap_delay_ms=10,
    )
    attempts = 0
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: waits.append(d))

    def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal attempts
        attempts += 1
        raise _StreamChunkTimeoutError("No streaming chunk received for 120.0s")

    result = middleware.wrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    assert "streaming response was interrupted" in result.content
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert attempts == 2
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(waits) == 1


@pytest.mark.anyio
async def test_async_stream_chunk_timeout_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(
        retry_max_attempts=3,
        retry_base_delay_ms=10,
        retry_cap_delay_ms=10,
    )
    attempts = 0
    waits: list[float] = []

    async def fake_sleep(d: float) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        waits.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal attempts
        attempts += 1
        raise _StreamChunkTimeoutError("No streaming chunk received for 120.0s")

    result = await middleware.awrap_model_call(SimpleNamespace(), handler)

    assert isinstance(result, AIMessage)
    assert "streaming response was interrupted" in result.content
    assert attempts == 2
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(waits) == 1


def test_max_attempts_for_returns_override_for_stream_chunk_timeout() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=3)
    exc = _StreamChunkTimeoutError("upstream stalled")
    exc.__class__.__name__ = "StreamChunkTimeoutError"

    assert middleware._max_attempts_for(exc) == 2


def test_max_attempts_for_falls_back_to_default_for_unlisted_exception() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=3)

    read_err = _ReadError("conn reset")
    read_err.__class__.__name__ = "ReadError"
    proto_err = _RemoteProtocolError("peer closed")
    proto_err.__class__.__name__ = "RemoteProtocolError"

    assert middleware._max_attempts_for(read_err) == 3
    assert middleware._max_attempts_for(proto_err) == 3
    assert middleware._max_attempts_for(FakeError("boom")) == 3


def test_max_attempts_for_override_never_exceeds_user_cap() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=1)
    exc = _StreamChunkTimeoutError("upstream stalled")
    exc.__class__.__name__ = "StreamChunkTimeoutError"

    assert middleware._max_attempts_for(exc) == 1


def test_user_message_for_stream_chunk_timeout_mentions_split_or_shorten() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = _StreamChunkTimeoutError("No streaming chunk received for 120.0s")
    exc.__class__.__name__ = "StreamChunkTimeoutError"

    message = middleware._build_user_message(exc, reason="transient")

    assert "streaming response was interrupted" in message
    assert "split" in message or "shorten" in message
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert "temporarily unavailable" not in message


def test_user_message_for_remote_protocol_error_uses_generic_transient_copy() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = _RemoteProtocolError("Server closed connection unexpectedly")
    exc.__class__.__name__ = "RemoteProtocolError"

    message = middleware._build_user_message(exc, reason="transient")

    assert "temporarily unavailable" in message
    assert "streaming response was interrupted" not in message


def test_user_message_for_read_error_uses_generic_transient_copy() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = FakeError("connection dropped mid-stream")
    exc.__class__.__name__ = "ReadError"

    message = middleware._build_user_message(exc, reason="transient")

    assert "temporarily unavailable" in message
    assert "streaming response was interrupted" not in message


def test_user_message_for_generic_transient_keeps_legacy_copy() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = FakeError("server busy", status_code=503)

    message = middleware._build_user_message(exc, reason="transient")

    assert "temporarily unavailable" in message
    assert "streaming response was interrupted" not in message


def test_user_message_for_quota_unchanged() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = FakeError("insufficient_quota", status_code=429, code="insufficient_quota")

    message = middleware._build_user_message(exc, reason="quota")

    assert "out of quota" in message
    assert "streaming response was interrupted" not in message


def test_classify_error_index_error_is_retriable_transient() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware()
    exc = IndexError("list index out of range")
    retriable, reason = middleware._classify_error(exc)
    assert retriable is True
    assert reason == "transient"


def test_async_index_error_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=3, retry_base_delay_ms=10, retry_cap_delay_ms=10)
    attempts = 0

    async def fake_sleep(_delay: float) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return None

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise IndexError("list index out of range")
        return AIMessage(content="ok")

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert attempts == 2


def test_async_index_error_exhausted_returns_user_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    middleware = _build_middleware(retry_max_attempts=2, retry_base_delay_ms=10, retry_cap_delay_ms=10)

    async def fake_sleep(_delay: float) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return None

    async def handler(_request) -> AIMessage:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise IndexError("list index out of range")

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = asyncio.run(middleware.awrap_model_call(SimpleNamespace(), handler))

    assert isinstance(result, AIMessage)
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_reason"] == "transient"
    assert result.additional_kwargs["error_type"] == "IndexError"
    assert "temporarily unavailable" in str(result.content)
