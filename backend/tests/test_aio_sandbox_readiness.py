"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox import backend as readiness


class _FakeAsyncClient:
    """归集“该项异步客户端”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
    def __init__(self, *, responses: list[object], calls: list[str], timeout: float, request_timeouts: list[float] | None = None) -> None:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self._responses = responses
        self._calls = calls
        self._timeout = timeout
        self._request_timeouts = request_timeouts

    async def __aenter__(self) -> _FakeAsyncClient:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return None

    async def get(self, url: str, *, timeout: float):
        """为“获取”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self._calls.append(url)
        if self._request_timeouts is not None:
            self._request_timeouts.append(timeout)
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _FakeLoop:
    """归集“该项该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
    def __init__(self, times: list[float]) -> None:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self._times = times
        self._index = 0

    def time(self) -> float:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        value = self._times[self._index]
        self._index += 1
        return value


@pytest.mark.anyio
async def test_wait_for_sandbox_ready_async_uses_nonblocking_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证“该项该项沙箱就绪异步使用该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_client(*, timeout: float):
        """为“该项客户端”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return _FakeAsyncClient(
            responses=[SimpleNamespace(status_code=503), SimpleNamespace(status_code=200)],
            calls=calls,
            timeout=timeout,
        )

    async def fake_sleep(delay: float) -> None:
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        sleeps.append(delay)

    monkeypatch.setattr(readiness.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(readiness.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("requests.get should not be used")))
    monkeypatch.setattr(readiness.time, "sleep", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("time.sleep should not be used")))

    assert await readiness.wait_for_sandbox_ready_async("http://sandbox", timeout=5, poll_interval=0.05) is True

    assert calls == ["http://sandbox/v1/sandbox", "http://sandbox/v1/sandbox"]
    assert sleeps == [0.05]


@pytest.mark.anyio
async def test_wait_for_sandbox_ready_async_retries_request_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证“该项该项沙箱就绪异步该项请求该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_client(*, timeout: float):
        """为“该项客户端”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return _FakeAsyncClient(
            responses=[readiness.httpx.ConnectError("not ready"), SimpleNamespace(status_code=200)],
            calls=calls,
            timeout=timeout,
        )

    async def fake_sleep(delay: float) -> None:
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        sleeps.append(delay)

    monkeypatch.setattr(readiness.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)

    assert await readiness.wait_for_sandbox_ready_async("http://sandbox", timeout=5, poll_interval=0.01) is True

    assert len(calls) == 2
    assert sleeps == [0.01]


@pytest.mark.anyio
async def test_wait_for_sandbox_ready_async_clamps_request_and_sleep_to_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证“该项该项沙箱就绪异步该项请求该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    calls: list[str] = []
    request_timeouts: list[float] = []
    sleeps: list[float] = []

    def fake_client(*, timeout: float):
        """为“该项客户端”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return _FakeAsyncClient(
            responses=[SimpleNamespace(status_code=503)],
            calls=calls,
            timeout=timeout,
            request_timeouts=request_timeouts,
        )

    async def fake_sleep(delay: float) -> None:
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        sleeps.append(delay)

    monkeypatch.setattr(readiness.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(readiness.asyncio, "get_running_loop", lambda: _FakeLoop([100.0, 100.5, 101.75, 102.0]))

    assert await readiness.wait_for_sandbox_ready_async("http://sandbox", timeout=2, poll_interval=1.0) is False

    assert calls == ["http://sandbox/v1/sandbox"]
    assert request_timeouts == [1.5]
    assert sleeps == [0.25]
