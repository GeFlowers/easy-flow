"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import types

import pytest

from deerflow.community.boxlite.box import BoxliteBox
from deerflow.community.boxlite.provider import BoxliteProvider, _import_simplebox

# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


class _FakeBox:
    """归集“该项隔离容器”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def __init__(self, *, image=None, name=None, memory_mib=None, cpus=None, **kwargs):
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self.id = name or "auto-gen-id"
        self.name = name
        self._image = image
        self._started = False
        self._stopped = False
        self._exec_history: list[tuple] = []

    async def start(self):
        """为“启动”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self._started = True

    async def exec(self, *argv, env=None, timeout=None):
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self._exec_history.append((argv, env, timeout))
        _FakeResult = type("_FakeResult", (), {"stdout": "", "stderr": "", "exit_code": 0})
        # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        if len(argv) >= 3 and argv[0] == "sh" and argv[1] == "-lc" and argv[2] == "echo ok":
            return type("_FakeResult", (), {"stdout": "ok\n", "stderr": "", "exit_code": 0})()
        return _FakeResult()

    async def stop(self):
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self._stopped = True


def _fake_run(coro, *, timeout=None):
    """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    return asyncio.run(coro)


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def _stub_config(sandbox_attrs=None):
    """为“该项配置”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    attrs = sandbox_attrs or {}
    stub = types.SimpleNamespace(sandbox=types.SimpleNamespace(**attrs))
    return stub


def _no_boxlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """为“该项轻量隔离容器”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    monkeypatch.setitem(sys.modules, "boxlite", None)


@pytest.fixture(autouse=True)
def _no_existing_boxlite_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    """为“该项该项轻量隔离容器该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""

    class _EmptyRuntime:
        """归集“空值运行时”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        def start(self):
            """为“启动”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return self

        def stop(self):
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            pass

        def list_info(self):
            """为“列出该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return []

    class _EmptyBoxlite:
        """归集“空值轻量隔离容器”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        @staticmethod
        def default():
            """为“默认值”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return _EmptyRuntime()

    monkeypatch.setattr("deerflow.community.boxlite.provider._import_sync_boxlite_runtime", lambda: _EmptyBoxlite)


def test_import_simplebox_missing_raises_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证“导入该项缺失抛出该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _no_boxlite(monkeypatch)
    with pytest.raises(ImportError, match=r"deerflow-harness\[boxlite\]"):
        _import_simplebox()


def test_acquire_without_boxlite_raises_and_shuts_down_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    """验证“获取不使用轻量隔离容器抛出该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    stub = types.SimpleNamespace(sandbox=types.SimpleNamespace())
    monkeypatch.setattr("deerflow.community.boxlite.provider.get_app_config", lambda: stub)
    _no_boxlite(monkeypatch)

    provider = BoxliteProvider()
    try:
        with pytest.raises(ImportError, match=r"deerflow-harness\[boxlite\]"):
            provider.acquire("thread-1", user_id="u")
    finally:
        provider.shutdown()  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    provider.shutdown()


def test_guard_traversal() -> None:
    """验证“防护越界遍历”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert BoxliteBox._guard_traversal("/mnt/user-data/workspace/a.txt") == "/mnt/user-data/workspace/a.txt"
    assert BoxliteBox._guard_traversal("relative/ok.txt") == "relative/ok.txt"
    with pytest.raises(PermissionError):
        BoxliteBox._guard_traversal("/mnt/user-data/../etc/passwd")
    with pytest.raises(ValueError):
        BoxliteBox._guard_traversal("")


def test_download_file_guards_reject_before_touching_box() -> None:
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    """验证“下载文件该项该项该项该项隔离容器”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    def _fail_run(_coro: object) -> None:
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        raise AssertionError("download_file must reject the path before running a command")

    box = BoxliteBox("box-id", box=object(), run=_fail_run)
    with pytest.raises(PermissionError):
        box.download_file("/etc/passwd")  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    with pytest.raises(PermissionError):
        box.download_file("/mnt/user-data/../etc/passwd")  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_execute_command_rejects_invalid_env_key() -> None:
    """验证“执行命令拒绝非法环境变量密钥”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    def _fail_run(_coro: object) -> None:
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        raise AssertionError("execute_command must reject a bad env key before running")

    box = BoxliteBox("box-id", box=object(), run=_fail_run)
    with pytest.raises(ValueError, match=r"POSIX"):
        box.execute_command("echo hi", env={"BAD KEY": "x"})


def test_execute_command_forwards_timeout_to_sdk_and_loop_runner() -> None:
    """验证“执行命令转发超时该项开发工具包该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    run_timeouts: list[float | None] = []

    def _recording_run(coro, *, timeout=None):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        run_timeouts.append(timeout)
        return asyncio.run(coro)

    fake = _FakeBox(name="box-id")
    box = BoxliteBox("box-id", box=fake, run=_recording_run)

    output = box.execute_command("echo ok", timeout=5)

    assert "ok" in output
    assert fake._exec_history[-1] == (("sh", "-lc", "echo ok"), None, 5)
    assert run_timeouts == [5]


def test_execute_command_invalidates_box_on_terminal_transport_error() -> None:
    """验证“执行命令该项隔离容器该项终止传输错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    invalidated: list[tuple[str, str]] = []

    def _failing_run(coro, *, timeout=None):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        coro.close()
        raise RuntimeError("vsock disconnected")

    box = BoxliteBox(
        "box-id",
        box=_FakeBox(name="box-id"),
        run=_failing_run,
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )

    output = box.execute_command("echo hi")

    assert output == "Error: vsock disconnected"
    assert invalidated == [("box-id", "vsock disconnected")]


def test_execute_command_does_not_invalidate_on_regular_command_error() -> None:
    """验证“执行命令该项该项该项该项该项命令错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    invalidated: list[tuple[str, str]] = []

    def _failing_run(coro, *, timeout=None):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        coro.close()
        raise RuntimeError("user command failed")

    box = BoxliteBox(
        "box-id",
        box=_FakeBox(name="box-id"),
        run=_failing_run,
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )

    output = box.execute_command("echo hi")

    assert output == "Error: user command failed"
    assert invalidated == []


def test_execute_command_does_not_invalidate_on_retryable_transport_message() -> None:
    """验证“执行命令该项该项该项该项该项传输该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    invalidated: list[tuple[str, str]] = []

    def _failing_run(coro, *, timeout=None):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        coro.close()
        raise RuntimeError("transport not ready, retry later")

    box = BoxliteBox(
        "box-id",
        box=_FakeBox(name="box-id"),
        run=_failing_run,
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )

    output = box.execute_command("echo hi")

    assert output == "Error: transport not ready, retry later"
    assert invalidated == []


def test_execute_command_uses_overridable_terminal_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证“执行命令使用该项终止该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    invalidated: list[tuple[str, str]] = []
    monkeypatch.setattr(BoxliteBox, "TERMINAL_ERROR_MARKERS", ("custom terminal marker",))
    monkeypatch.setattr(BoxliteBox, "RETRYABLE_ERROR_MARKERS", ())

    def _failing_run(coro, *, timeout=None):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        coro.close()
        raise RuntimeError("custom terminal marker")

    box = BoxliteBox(
        "box-id",
        box=_FakeBox(name="box-id"),
        run=_failing_run,
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )

    output = box.execute_command("echo hi")

    assert output == "Error: custom terminal marker"
    assert invalidated == [("box-id", "custom terminal marker")]


def test_execute_command_closed_box_returns_without_error_log(caplog) -> None:
    """验证“执行命令已关闭隔离容器返回不使用错误该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    box = BoxliteBox("box-id", box=_FakeBox(name="box-id"), run=_fake_run)
    box.close()

    with caplog.at_level(logging.ERROR, logger="deerflow.community.boxlite.box"):
        output = box.execute_command("echo hi")

    assert output == "Error: sandbox has been closed"
    assert "Failed to execute command in BoxLite box" not in caplog.text


def test_sandbox_id_deterministic(monkeypatch):
    """验证“沙箱标识该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    provider = BoxliteProvider()
    id1 = provider._sandbox_id("thread-1", "user-a")
    id2 = provider._sandbox_id("thread-1", "user-a")
    assert id1 == id2
    assert len(id1) == 8


def test_sandbox_id_different_users(monkeypatch):
    """验证“沙箱标识不同该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    provider = BoxliteProvider()
    id_a = provider._sandbox_id("thread-1", "user-a")
    id_b = provider._sandbox_id("thread-1", "user-b")
    assert id_a != id_b


def test_sandbox_id_different_threads(monkeypatch):
    """验证“沙箱标识不同该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    provider = BoxliteProvider()
    id_a = provider._sandbox_id("thread-1", "user-a")
    id_b = provider._sandbox_id("thread-2", "user-a")
    assert id_a != id_b


def test_idle_timeout_zero_is_preserved_and_disables_reaper(monkeypatch):
    """验证“该项超时该项该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"idle_timeout": 0}),
    )

    provider = BoxliteProvider()

    assert provider._config["idle_timeout"] == 0
    assert provider._idle_checker_thread is None
    provider.shutdown()


def test_create_box_passes_prefixed_sandbox_id_as_name(monkeypatch):
    """验证“创建隔离容器该项该项沙箱标识该项名称”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    created_boxes = []

    class _RecordingBox(_FakeBox):
        """归集“该项隔离容器”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        def __init__(self, **kwargs):
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            super().__init__(**kwargs)
            created_boxes.append(kwargs)

    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _RecordingBox,
    )

    provider = BoxliteProvider()
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    provider._loop.run = _fake_run

    box = provider._create_box("test-sandbox-id")
    assert len(created_boxes) == 1
    assert created_boxes[0]["name"] == "deer-flow-boxlite-test-sandbox-id"
    assert box.id == "test-sandbox-id"


def test_startup_reconciliation_adopts_prefixed_existing_boxes(monkeypatch):
    """验证“启动该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    stopped: list[str] = []

    class _NativeBox:
        """归集“该项隔离容器”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        def stop(self):
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            stopped.append("adopted")

    class _Runtime:
        """归集“运行时”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        def start(self):
            """为“启动”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return self

        def stop(self):
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            pass

        def list_info(self):
            """为“列出该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return [
                types.SimpleNamespace(name="deer-flow-boxlite-adopted"),
                types.SimpleNamespace(name="unrelated-box"),
                types.SimpleNamespace(name=None),
            ]

        def get(self, name):
            """为“获取”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            if name == "deer-flow-boxlite-adopted":
                return _NativeBox()
            raise AssertionError(f"unexpected box lookup: {name}")

    class _Boxlite:
        """归集“轻量隔离容器”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        @staticmethod
        def default():
            """为“默认值”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return _Runtime()

    monkeypatch.setattr("deerflow.community.boxlite.provider._import_sync_boxlite_runtime", lambda: _Boxlite)

    provider = BoxliteProvider()

    assert list(provider._warm_pool) == ["adopted"]
    adopted_box = provider._warm_pool["adopted"][0]
    assert adopted_box.id == "adopted"

    provider.shutdown()
    assert stopped == ["adopted"]


def test_release_parks_in_warm_pool(monkeypatch):
    """验证“该项该项该项预热池”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # 获得一个盒子
    sid = provider.acquire("thread-1", user_id="u1")

    # 验证框已激活
    assert sid in provider._boxes
    assert sid not in provider._warm_pool

    # 发布
    provider.release(sid)

    # 验证框是否在热池中，未激活
    assert sid not in provider._boxes
    assert sid in provider._warm_pool
    box, ts = provider._warm_pool[sid]
    assert isinstance(box, BoxliteBox)
    assert not box._box._stopped  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_acquire_reclaims_from_warm_pool(monkeypatch):
    """验证“获取该项该项预热池”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # 首先获取→创建
    sid1 = provider.acquire("thread-1", user_id="u1")
    provider.release(sid1)

    # 第二次获取 → 应该从热池中回收
    sid2 = provider.acquire("thread-1", user_id="u1")
    assert sid1 == sid2  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert sid2 in provider._boxes
    assert sid2 not in provider._warm_pool


def test_explicit_recent_reclaim_skip_avoids_health_check(monkeypatch):
    """验证“显式最近回收跳过该项健康检查该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)
    box, _ = provider._warm_pool[sid]

    def _fail_if_called(*args, **kwargs):
        """为“该项该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        raise AssertionError("health check should be skipped for recently released boxes")

    monkeypatch.setattr(box, "execute_command", _fail_if_called)

    reclaimed = provider._reclaim_warm_pool(sid)
    assert reclaimed == sid
    assert sid in provider._boxes
    assert sid not in provider._warm_pool

    provider.shutdown()


def test_recent_reclaim_validates_by_default(monkeypatch):
    """验证“最近回收该项该项默认值”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)
    box, _ = provider._warm_pool[sid]
    calls = 0
    original_execute = box.execute_command

    def _record_health_check(command: str, *args, **kwargs):
        """为“该项健康检查该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        nonlocal calls
        calls += 1
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(box, "execute_command", _record_health_check)

    reclaimed = provider._reclaim_warm_pool(sid)
    assert reclaimed == sid
    assert calls == 1
    assert sid in provider._boxes
    assert sid not in provider._warm_pool

    provider.shutdown()


def test_default_recent_reclaim_drops_dead_warm_box(monkeypatch):
    """验证“默认值最近回收该项失效预热隔离容器”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)
    box, _ = provider._warm_pool[sid]

    def _dead_health_check(command: str, *args, **kwargs):
        """为“失效健康检查该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        assert command == "echo ok"
        return "Error: vsock disconnected"

    monkeypatch.setattr(box, "execute_command", _dead_health_check)

    reclaimed = provider._reclaim_warm_pool(sid)
    assert reclaimed is None
    assert sid not in provider._boxes
    assert sid not in provider._warm_pool
    assert sid not in provider._skip_health_check_warm_ids
    assert box.is_closed is True

    provider.shutdown()


def test_dead_active_box_invalidation_closes_adapter(monkeypatch):
    """验证“失效活动隔离容器该项该项适配器”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    box = provider.get(sid)
    assert box is not None

    def _dead_run(coro, *, timeout=None):
        """为“失效该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        coro.close()
        raise RuntimeError("vsock disconnected")

    box._run = _dead_run

    output = box.execute_command("echo hi")
    assert output == "Error: vsock disconnected"
    assert box._closed is True
    assert provider.get(sid) is None

    provider.shutdown()


def test_adopted_warm_pool_box_still_health_checks(monkeypatch):
    """验证“该项预热池隔离容器该项健康检查该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )

    provider = BoxliteProvider()
    adopted = BoxliteBox(
        "adopted",
        _FakeBox(name="deer-flow-boxlite-adopted"),
        _fake_run,
        default_env={},
    )
    provider._warm_pool["adopted"] = (adopted, time.time())
    calls = 0
    original_execute = adopted.execute_command

    def _record_health_check(command: str, *args, **kwargs):
        """为“该项健康检查该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        nonlocal calls
        calls += 1
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(adopted, "execute_command", _record_health_check)

    reclaimed = provider._reclaim_warm_pool("adopted")
    assert reclaimed == "adopted"
    assert calls == 1
    assert "adopted" in provider._boxes
    assert "adopted" not in provider._warm_pool

    provider.shutdown()


def test_dead_active_box_is_invalidated_after_command_failure(monkeypatch):
    """验证“失效活动隔离容器该项该项该项命令失败”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    box = provider.get(sid)
    assert box is not None

    def _dead_run(coro, *, timeout=None):
        """为“失效该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        coro.close()
        raise RuntimeError("vsock disconnected")

    box._run = _dead_run

    output = box.execute_command("echo hi")
    assert output == "Error: vsock disconnected"
    assert provider.get(sid) is None

    sid2 = provider.acquire("thread-1", user_id="u1")
    assert sid2 == sid
    assert provider.get(sid2) is not None

    provider.shutdown()


def test_stale_closed_adapter_cannot_invalidate_recreated_box(monkeypatch):
    """验证“过期已关闭适配器该项该项该项隔离容器”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    stale_box = provider.get(sid)
    assert stale_box is not None

    def _dead_run(coro, *, timeout=None):
        """为“失效该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        coro.close()
        raise RuntimeError("vsock disconnected")

    stale_box._run = _dead_run
    stale_box.execute_command("echo hi")
    assert provider.get(sid) is None

    provider._loop.run = _fake_run
    sid2 = provider.acquire("thread-1", user_id="u1")
    replacement = provider.get(sid2)
    assert sid2 == sid
    assert replacement is not None
    assert replacement is not stale_box

    stale_box.execute_command("echo again")

    assert provider.get(sid) is replacement
    assert replacement._closed is False

    provider.shutdown()


def test_acquire_different_threads_dont_reclaim_each_other(monkeypatch):
    """验证“获取不同该项该项回收该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid_a = provider.acquire("thread-a", user_id="u1")
    provider.release(sid_a)

    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    sid_b = provider.acquire("thread-b", user_id="u1")
    assert sid_b != sid_a  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert sid_a in provider._warm_pool  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert sid_b in provider._boxes  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_warm_pool_reclaim_failed_health_check_creates_new(monkeypatch):
    """验证“预热池回收失败健康检查该项该项新的”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid1 = provider.acquire("thread-1", user_id="u1")
    provider.release(sid1)
    assert sid1 in provider._warm_pool

    # 损坏暖池盒：关闭它，因此运行状况检查失败
    box, _ = provider._warm_pool[sid1]
    box.close()  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。

    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    sid2 = provider.acquire("thread-1", user_id="u1")
    assert sid2 == sid1  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert sid2 in provider._boxes
    replacement = provider.get(sid2)
    assert replacement is not None
    assert replacement is not box
    assert replacement._closed is False


def test_concurrent_same_thread_acquire_creates_one_box(monkeypatch):
    """验证“并发相同线程获取该项该项隔离容器”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run
    original_create_box = provider._create_box
    create_started = threading.Event()
    created: list[str] = []

    def slow_create_box(sandbox_id: str) -> BoxliteBox:
        """为“该项创建隔离容器”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        create_started.set()
        time.sleep(0.1)
        created.append(sandbox_id)
        return original_create_box(sandbox_id)

    provider._create_box = slow_create_box  # type: ignore[method-assign]
    results: list[str] = []

    def acquire() -> None:
        """为“获取”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        results.append(provider.acquire("thread-1", user_id="u1"))

    first = threading.Thread(target=acquire)
    second = threading.Thread(target=acquire)
    first.start()
    assert create_started.wait(timeout=2)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert len(results) == 2
    assert results[0] == results[1]
    assert len(created) == 1
    assert results[0] in provider._boxes
    provider.shutdown()


def test_release_during_shutdown_closes_instead_of_reparking(monkeypatch):
    """验证“该项该项关闭该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    box = provider._boxes[sid]
    with provider._lock:
        provider._shutdown_called = True

    provider.release(sid)

    assert sid not in provider._boxes
    assert sid not in provider._warm_pool
    assert box._closed
    provider._loop.close()


def test_reset_parks_running_resources_for_later_cleanup(monkeypatch):
    """验证“重置该项运行中资源该项该项清理”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid_active = provider.acquire("thread-active", user_id="u1")
    sid_warm = provider.acquire("thread-warm", user_id="u1")
    provider.release(sid_warm)
    active_box = provider._boxes[sid_active]
    warm_box = provider._warm_pool[sid_warm][0]
    checker_thread = provider._idle_checker_thread
    loop_thread = provider._loop._thread

    provider.reset()

    assert provider._boxes == {}
    assert provider._warm_pool[sid_active][0] is active_box
    assert provider._warm_pool[sid_warm][0] is warm_box
    assert provider._thread_boxes == {}
    assert provider._acquire_locks == {}
    assert not active_box._closed
    assert not warm_box._closed
    assert not provider._shutdown_called
    assert not provider._idle_checker_stop.is_set()
    assert checker_thread is not None
    assert checker_thread.is_alive()
    assert loop_thread.is_alive()

    provider.shutdown()
    assert active_box._closed
    assert warm_box._closed
    assert provider._idle_checker_stop.is_set()
    assert not checker_thread.is_alive()


def test_reset_parked_resources_are_reaped_after_idle_timeout(monkeypatch):
    """验证“重置该项资源该项该项该项该项超时”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid_active = provider.acquire("thread-active", user_id="u1")
    sid_warm = provider.acquire("thread-warm", user_id="u1")
    provider.release(sid_warm)
    active_box = provider._boxes[sid_active]
    warm_box = provider._warm_pool[sid_warm][0]

    provider.reset()

    provider._warm_pool[sid_active] = (active_box, time.time() - 9999)
    provider._warm_pool[sid_warm] = (warm_box, time.time() - 9999)
    provider._reap_expired_warm(idle_timeout=1)

    assert provider._warm_pool == {}
    assert active_box._closed
    assert warm_box._closed
    provider.shutdown()


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_idle_reaper_destroys_expired_warm_boxes(monkeypatch):
    """验证“该项该项该项过期预热该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    # 使用非常短的检查间隔，以便收割机快速运行
    monkeypatch.setattr(BoxliteProvider, "IDLE_CHECK_INTERVAL", 0.1)
    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # 获取一个盒子并将其释放到温水池中
    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)

    assert sid in provider._warm_pool

    # 回溯热池时间戳，使其看起来过期很久
    warm_box = provider._warm_pool[sid][0]
    provider._warm_pool[sid] = (warm_box, time.time() - 9999)

    # 等待足够长的时间，让收割者发现并摧毁它
    time.sleep(0.3)

    # 盒子应该从温水池中消失并关闭
    assert sid not in provider._warm_pool
    assert warm_box._closed

    provider.shutdown()


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_replica_enforcement_evicts_oldest_warm(monkeypatch):
    """验证“该项该项该项该项预热”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"replicas": 2}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # 用来自不同线程的 2 个盒子填充热池
    sid_a = provider.acquire("thread-a", user_id="u1")
    provider.release(sid_a)

    sid_b = provider.acquire("thread-b", user_id="u1")
    provider.release(sid_b)

    assert len(provider._warm_pool) == 2
    assert sid_a in provider._warm_pool
    assert sid_b in provider._warm_pool

    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    box_a = provider._warm_pool[sid_a][0]
    provider._warm_pool[sid_a] = (box_a, time.time() - 100)
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    box_b = provider._warm_pool[sid_b][0]
    provider._warm_pool[sid_b] = (box_b, time.time())

    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 获取第三个线程会触发副本强制执行：
    sid_c = provider.acquire("thread-c", user_id="u1")

    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert sid_a not in provider._warm_pool
    assert box_a._closed
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert sid_b in provider._warm_pool
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert sid_c in provider._boxes
    assert sid_c not in provider._warm_pool

    provider.shutdown()


def test_replica_enforcement_counts_active_and_warm(monkeypatch):
    """验证“该项该项该项活动该项预热”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"replicas": 2}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid_active = provider.acquire("thread-active", user_id="u1")
    sid_warm = provider.acquire("thread-warm", user_id="u1")
    provider.release(sid_warm)
    warm_box = provider._warm_pool[sid_warm][0]

    sid_new = provider.acquire("thread-new", user_id="u1")

    assert sid_active in provider._boxes
    assert sid_new in provider._boxes
    assert sid_warm not in provider._warm_pool
    assert warm_box._closed
    provider.shutdown()


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_shutdown_stops_idle_reaper_and_destroys_all_boxes(monkeypatch):
    """验证“关闭该项该项该项该项该项全部该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # 创建 1 个活动盒子（线程 1）和 1 个暖池盒子（线程 2 已释放）
    sid_active = provider.acquire("thread-1", user_id="u1")
    sid_warm = provider.acquire("thread-2", user_id="u1")
    provider.release(sid_warm)

    assert sid_active in provider._boxes
    assert sid_warm in provider._warm_pool

    # 关机前获取盒子参考
    box_active = provider._boxes[sid_active]
    box_warm = provider._warm_pool[sid_warm][0]

    # 记住空闲检查线程
    checker_thread = provider._idle_checker_thread

    provider.shutdown()

    # 空闲检查器应停止
    assert provider._idle_checker_stop.is_set()
    assert checker_thread is not None
    assert not checker_thread.is_alive()

    # 所有盒子（活动+温暖）应关闭
    assert box_active._closed
    assert box_warm._closed

    # 所有集合应为空
    assert len(provider._boxes) == 0
    assert len(provider._warm_pool) == 0
    assert len(provider._thread_boxes) == 0
