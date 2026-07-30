"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.config.paths import Paths, join_host_path
from deerflow.runtime.user_context import reset_current_user, set_current_user

# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_ensure_thread_dirs_creates_acp_workspace(tmp_path):
    """验证“该项线程该项该项智能体通信协议该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    paths = Paths(base_dir=tmp_path)
    paths.ensure_thread_dirs("thread-1")

    assert (tmp_path / "threads" / "thread-1" / "user-data" / "workspace").exists()
    assert (tmp_path / "threads" / "thread-1" / "user-data" / "uploads").exists()
    assert (tmp_path / "threads" / "thread-1" / "user-data" / "outputs").exists()
    assert (tmp_path / "threads" / "thread-1" / "acp-workspace").exists()


def test_ensure_thread_dirs_acp_workspace_is_world_writable(tmp_path):
    """验证“该项线程该项智能体通信协议该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    paths = Paths(base_dir=tmp_path)
    paths.ensure_thread_dirs("thread-2")

    acp_dir = tmp_path / "threads" / "thread-2" / "acp-workspace"
    mode = oct(acp_dir.stat().st_mode & 0o777)
    assert mode == oct(0o777)


def test_host_thread_dir_rejects_invalid_thread_id(tmp_path):
    """验证“主机线程目录拒绝非法线程标识”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    paths = Paths(base_dir=tmp_path)

    with pytest.raises(ValueError, match="Invalid thread_id"):
        paths.host_thread_dir("../escape")


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def _make_provider(tmp_path):
    """为“构造提供方”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    with patch.object(aio_mod.AioSandboxProvider, "_start_idle_checker"):
        provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
        provider._config = {}
        provider._sandboxes = {}
        provider._lock = MagicMock()
        provider._idle_checker_stop = MagicMock()
    return provider


def test_get_thread_mounts_includes_acp_workspace(tmp_path, monkeypatch):
    """验证“获取线程该项该项智能体通信协议该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: None)

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-3")

    container_paths = {m[1]: (m[0], m[2]) for m in mounts}

    assert "/mnt/acp-workspace" in container_paths, "ACP workspace mount is missing"
    expected_host = str(tmp_path / "threads" / "thread-3" / "acp-workspace")
    actual_host, read_only = container_paths["/mnt/acp-workspace"]
    assert actual_host == expected_host
    assert read_only is True, "ACP workspace should be read-only inside the sandbox"


def test_get_thread_mounts_includes_user_data_dirs(tmp_path, monkeypatch):
    """验证“获取线程该项该项用户该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-4")
    container_paths = {m[1] for m in mounts}

    assert "/mnt/user-data/workspace" in container_paths
    assert "/mnt/user-data/uploads" in container_paths
    assert "/mnt/user-data/outputs" in container_paths


def test_get_thread_mounts_uses_explicit_user_id(tmp_path, monkeypatch):
    """验证“获取线程该项使用显式用户标识”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: "default")

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-4", user_id="ou-user")
    container_paths = {container_path: host_path for host_path, container_path, _ in mounts}

    assert container_paths["/mnt/user-data/workspace"] == str(tmp_path / "users" / "ou-user" / "threads" / "thread-4" / "user-data" / "workspace")
    assert container_paths["/mnt/user-data/uploads"] == str(tmp_path / "users" / "ou-user" / "threads" / "thread-4" / "user-data" / "uploads")
    assert container_paths["/mnt/user-data/outputs"] == str(tmp_path / "users" / "ou-user" / "threads" / "thread-4" / "user-data" / "outputs")


def test_join_host_path_preserves_windows_drive_letter_style():
    """验证“该项主机路径保留视窗系统该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    base = r"C:\Users\demo\deer-flow\backend\.deer-flow"

    joined = join_host_path(base, "threads", "thread-9", "user-data", "outputs")

    assert joined == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-9\user-data\outputs"


def test_get_thread_mounts_preserves_windows_host_path_style(tmp_path, monkeypatch):
    """验证“获取线程该项保留视窗系统主机路径该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    monkeypatch.setenv("DEER_FLOW_HOST_BASE_DIR", r"C:\Users\demo\deer-flow\backend\.deer-flow")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: None)

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-10")

    container_paths = {container_path: host_path for host_path, container_path, _ in mounts}

    assert container_paths["/mnt/user-data/workspace"] == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-10\user-data\workspace"
    assert container_paths["/mnt/user-data/uploads"] == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-10\user-data\uploads"
    assert container_paths["/mnt/user-data/outputs"] == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-10\user-data\outputs"
    assert container_paths["/mnt/acp-workspace"] == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-10\acp-workspace"


def test_discover_or_create_only_unlocks_when_lock_succeeds(tmp_path, monkeypatch):
    """验证“发现该项创建仅该项当锁该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._discover_or_create_with_lock = aio_mod.AioSandboxProvider._discover_or_create_with_lock.__get__(
        provider,
        aio_mod.AioSandboxProvider,
    )

    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        aio_mod,
        "_lock_file_exclusive",
        lambda _lock_file: (_ for _ in ()).throw(RuntimeError("lock failed")),
    )

    unlock_calls: list[object] = []
    monkeypatch.setattr(
        aio_mod,
        "_unlock_file",
        lambda lock_file: unlock_calls.append(lock_file),
    )

    with patch.object(provider, "_create_sandbox", return_value="sandbox-id"):
        with pytest.raises(RuntimeError, match="lock failed"):
            provider._discover_or_create_with_lock("thread-5", "sandbox-5")

    assert unlock_calls == []


@pytest.mark.anyio
async def test_acquire_async_uses_async_readiness_polling(monkeypatch):
    """验证“获取异步使用异步该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(None)
    provider._config = {"replicas": 3}
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()
    provider._backend = SimpleNamespace(
        create=MagicMock(return_value=aio_mod.SandboxInfo(sandbox_id="sandbox-async", sandbox_url="http://sandbox")),
        destroy=MagicMock(),
        discover=MagicMock(return_value=None),
    )

    async_readiness_calls: list[tuple[str, int]] = []

    async def fake_wait_for_sandbox_ready_async(sandbox_url: str, timeout: int = 30, poll_interval: float = 1.0) -> bool:
        """为“该项该项该项沙箱就绪异步”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        async_readiness_calls.append((sandbox_url, timeout))
        return True

    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready_async", fake_wait_for_sandbox_ready_async)
    monkeypatch.setattr(
        aio_mod,
        "wait_for_sandbox_ready",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("sync readiness should not be used")),
    )

    sandbox_id = await provider._create_sandbox_async("thread-async", "sandbox-async", user_id="user-async")

    assert sandbox_id == "sandbox-async"
    assert async_readiness_calls == [("http://sandbox", 60)]
    assert provider._backend.destroy.call_count == 0
    assert provider._thread_sandboxes[("user-async", "thread-async")] == "sandbox-async"


@pytest.mark.anyio
async def test_discover_or_create_with_lock_async_offloads_lock_file_open_and_close(tmp_path, monkeypatch):
    """验证“发现该项创建使用锁异步该项锁文件该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._discover_or_create_with_lock_async = aio_mod.AioSandboxProvider._discover_or_create_with_lock_async.__get__(
        provider,
        aio_mod.AioSandboxProvider,
    )
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {("default", "thread-async-lock"): "sandbox-async-lock"}
    provider._sandboxes = {"sandbox-async-lock": aio_mod.AioSandbox(id="sandbox-async-lock", base_url="http://sandbox")}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()
    provider._backend = SimpleNamespace(discover=MagicMock(return_value=None))

    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    to_thread_calls: list[object] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        """为“该项该项线程”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        to_thread_calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(aio_mod.asyncio, "to_thread", fake_to_thread)

    sandbox_id = await provider._discover_or_create_with_lock_async("thread-async-lock", "sandbox-async-lock", user_id="default")

    assert sandbox_id == "sandbox-async-lock"
    assert aio_mod._open_lock_file in to_thread_calls
    assert any(getattr(func, "__name__", "") == "close" for func in to_thread_calls)


@pytest.mark.anyio
async def test_acquire_thread_lock_async_uses_dedicated_executor(monkeypatch):
    """验证“获取线程锁异步使用该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    lock = aio_mod.threading.Lock()

    async def fail_to_thread(*_args, **_kwargs):
        """为“该项该项线程”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        raise AssertionError("thread-lock acquisition must not use asyncio.to_thread")

    monkeypatch.setattr(aio_mod.asyncio, "to_thread", fail_to_thread)

    await aio_mod._acquire_thread_lock_async(lock)
    try:
        assert not lock.acquire(blocking=False)
    finally:
        lock.release()


@pytest.mark.anyio
async def test_acquire_async_cancellation_does_not_leak_thread_lock(tmp_path):
    """验证“获取异步该项该项该项该项线程锁”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    thread_id = "thread-cancel-lock"
    thread_lock = provider._get_thread_lock(thread_id, "default")
    thread_lock.acquire()

    task = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    await asyncio.sleep(0.05)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    thread_lock.release()
    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        acquired = thread_lock.acquire(blocking=False)
        if acquired:
            thread_lock.release()
            return
        await asyncio.sleep(0.01)

    pytest.fail("provider thread lock was leaked after cancelling acquire_async")


@pytest.mark.anyio
async def test_acquire_async_cancelled_waiter_does_not_block_successor(tmp_path, monkeypatch):
    """验证“获取异步已取消该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    async def fake_acquire_internal_async(thread_id: str | None, *, user_id: str) -> str:
        """为“该项获取内部异步”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        assert thread_id == "thread-successor-lock"
        assert user_id == "default"
        await asyncio.sleep(0)
        return "sandbox-successor"

    monkeypatch.setattr(provider, "_acquire_internal_async", fake_acquire_internal_async)

    thread_id = "thread-successor-lock"
    thread_lock = provider._get_thread_lock(thread_id, "default")
    thread_lock.acquire()

    cancelled_waiter = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    await asyncio.sleep(0.05)
    cancelled_waiter.cancel()
    try:
        await cancelled_waiter
    except asyncio.CancelledError:
        pass

    live_waiter = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    thread_lock.release()

    assert await asyncio.wait_for(live_waiter, timeout=1) == "sandbox-successor"

    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        acquired = thread_lock.acquire(blocking=False)
        if acquired:
            thread_lock.release()
            return
        await asyncio.sleep(0.01)

    pytest.fail("provider thread lock was not released after successor acquire_async")


@pytest.mark.anyio
async def test_acquire_internal_async_offloads_cached_reuse_health_check(tmp_path, monkeypatch):
    """验证“获取内部异步该项缓存该项健康检查该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, _sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-cached-async")
    provider._thread_sandboxes = {("default", "thread-cached-async"): "sandbox-cached-async"}
    provider._backend.is_alive = MagicMock(return_value=True)

    to_thread_calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        """为“该项该项线程”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        to_thread_calls.append((func, args))
        return func(*args, **kwargs)

    monkeypatch.setattr(aio_mod.asyncio, "to_thread", fake_to_thread)

    sandbox_id = await provider._acquire_internal_async("thread-cached-async", user_id="default")

    assert sandbox_id == "sandbox-cached-async"
    assert to_thread_calls == [(provider._reuse_in_process_sandbox, ("thread-cached-async",))]


def test_remote_backend_create_forwards_effective_user_id(monkeypatch):
    """验证“远程该项创建转发有效用户标识”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    remote_mod = importlib.import_module("deerflow.community.aio_sandbox.remote_backend")
    backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002")
    token = set_current_user(SimpleNamespace(id="user-7"))
    posted: dict = {}

    class _Response:
        """归集“响应”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        def raise_for_status(self):
            """为“该项该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return None

        def json(self):
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return {"sandbox_url": "http://sandbox.local"}

    def _post(url, json, timeout, headers=None):  # noqa: A002 - mirrors requests.post kwarg
        """为“提交”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        posted.update({"url": url, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr(remote_mod.requests, "post", _post)
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda user_id: True)

    try:
        backend.create("thread-42", "sandbox-42")
    finally:
        reset_current_user(token)

    assert posted["url"] == "http://provisioner:8002/api/sandboxes"
    assert posted["json"] == {
        "sandbox_id": "sandbox-42",
        "thread_id": "thread-42",
        "user_id": "user-7",
        "include_legacy_skills": True,
    }


def test_remote_backend_create_prefers_explicit_user_id(monkeypatch):
    """验证“远程该项创建该项显式用户标识”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    remote_mod = importlib.import_module("deerflow.community.aio_sandbox.remote_backend")
    backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002")
    posted: dict = {}

    class _Response:
        """归集“响应”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        def raise_for_status(self):
            """为“该项该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return None

        def json(self):
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            return {"sandbox_url": "http://sandbox.local"}

    def _post(url, json, timeout, headers=None):  # noqa: A002 - mirrors requests.post kwarg
        """为“提交”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        posted.update({"url": url, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr(remote_mod.requests, "post", _post)
    monkeypatch.setattr(remote_mod, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda user_id: False)

    backend.create("thread-42", "sandbox-42", user_id="ou-user")

    assert posted["json"]["user_id"] == "ou-user"
    assert posted["json"]["include_legacy_skills"] is False


# ── 沙盒客户端拆解（#2872） ──────────────────────────────────────────


def _make_provider_with_active_sandbox(tmp_path, sandbox_id: str):
    """为“构造提供方使用活动沙箱”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._warm_pool = {}
    provider._sandbox_infos = {
        sandbox_id: aio_mod.SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://sandbox-host"),
    }
    provider._thread_sandboxes = {}
    provider._last_activity = {sandbox_id: 0.0}
    provider._shutdown_called = False
    provider._idle_checker_thread = None
    provider._backend = SimpleNamespace(destroy=MagicMock())

    sandbox = MagicMock()
    sandbox.id = sandbox_id
    sandbox.close = MagicMock()
    provider._sandboxes = {sandbox_id: sandbox}
    return provider, sandbox, aio_mod


def test_release_closes_cached_sandbox_client(tmp_path):
    """验证“该项该项缓存沙箱客户端”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-rel")

    provider.release("sandbox-rel")

    sandbox.close.assert_called_once_with()
    # 沙箱停在暖池中（容器仍在运行）。
    assert "sandbox-rel" in provider._warm_pool
    assert "sandbox-rel" not in provider._sandboxes


def test_destroy_closes_cached_sandbox_client(tmp_path):
    """验证“该项该项缓存沙箱客户端”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-destroy")
    backend_destroy = provider._backend.destroy

    provider.destroy("sandbox-destroy")

    sandbox.close.assert_called_once_with()
    backend_destroy.assert_called_once()
    assert "sandbox-destroy" not in provider._sandboxes
    assert "sandbox-destroy" not in provider._sandbox_infos


def test_shutdown_closes_all_active_sandbox_clients(tmp_path):
    """验证“关闭该项全部活动沙箱该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-shut")

    provider.shutdown()

    sandbox.close.assert_called_once_with()
    provider._backend.destroy.assert_called_once()
    assert provider._sandboxes == {}


def test_release_swallows_close_errors(tmp_path, caplog):
    """验证“该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-rel-err")
    sandbox.close.side_effect = RuntimeError("boom")

    with caplog.at_level("WARNING"):
        provider.release("sandbox-rel-err")

    assert "Error closing sandbox sandbox-rel-err during release" in caplog.text
    # 仍移至热池：客户端拆卸失败不得阻止生命周期。
    assert "sandbox-rel-err" in provider._warm_pool


def test_get_uses_in_memory_registry_only(tmp_path):
    """验证“获取使用该项该项该项仅”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-dead")
    provider._backend.is_alive = MagicMock(side_effect=AssertionError("get must not call backend health checks"))

    assert provider.get("sandbox-dead") is sandbox


def test_acquire_drops_dead_cached_sandbox(tmp_path, monkeypatch):
    """验证“获取该项失效缓存沙箱”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-dead")
    provider._thread_locks = {}
    provider._thread_sandboxes = {("default", "thread-dead"): "sandbox-dead"}
    provider._config = {"replicas": 3}
    provider._backend.is_alive = MagicMock(return_value=False)
    provider._backend.discover = MagicMock(return_value=None)
    provider._backend.create = MagicMock(
        return_value=aio_mod.SandboxInfo(
            sandbox_id="sandbox-dead",
            sandbox_url="http://fresh-sandbox",
            container_name="deer-flow-sandbox-sandbox-dead",
        )
    )

    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_sandbox_id_for_thread", lambda _self, _thread_id, _user_id: "sandbox-dead")
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_get_extra_mounts", lambda _self, _thread_id, *, user_id=None: [])
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: None)
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, timeout=60: True)

    sandbox_id = provider.acquire("thread-dead", user_id="default")

    assert sandbox_id == "sandbox-dead"
    sandbox.close.assert_called_once_with()
    provider._backend.destroy.assert_called_once()
    provider._backend.create.assert_called_once()
    assert provider._thread_sandboxes[("default", "thread-dead")] == "sandbox-dead"
    assert provider._sandboxes["sandbox-dead"].base_url == "http://fresh-sandbox"


def test_acquire_keeps_cached_sandbox_when_health_check_errors(tmp_path):
    """验证“获取保留缓存沙箱当健康检查该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-transient")
    provider._thread_locks = {}
    provider._thread_sandboxes = {("default", "thread-transient"): "sandbox-transient"}
    provider._backend.is_alive = MagicMock(side_effect=OSError("docker daemon busy"))

    sandbox_id = provider.acquire("thread-transient", user_id="default")

    assert sandbox_id == "sandbox-transient"
    sandbox.close.assert_not_called()
    provider._backend.destroy.assert_not_called()
    assert provider._sandboxes["sandbox-transient"] is sandbox


def test_drop_unhealthy_sandbox_skips_recreated_entry(tmp_path):
    """验证“该项该项沙箱该项该项条目”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._warm_pool = {}
    provider._last_activity = {"sandbox-toctou": 1.0}
    provider._thread_sandboxes = {("default", "thread-toctou"): "sandbox-toctou"}
    old_info = aio_mod.SandboxInfo(sandbox_id="sandbox-toctou", sandbox_url="http://old-sandbox")
    new_info = aio_mod.SandboxInfo(sandbox_id="sandbox-toctou", sandbox_url="http://new-sandbox")
    new_sandbox = MagicMock()
    provider._sandbox_infos = {"sandbox-toctou": new_info}
    provider._sandboxes = {"sandbox-toctou": new_sandbox}
    provider._backend = SimpleNamespace(destroy=MagicMock())

    provider._drop_unhealthy_sandbox("sandbox-toctou", "stale health check", expected_info=old_info)

    new_sandbox.close.assert_not_called()
    provider._backend.destroy.assert_not_called()
    assert provider._sandbox_infos["sandbox-toctou"] is new_info
    assert provider._sandboxes["sandbox-toctou"] is new_sandbox
    assert provider._thread_sandboxes == {("default", "thread-toctou"): "sandbox-toctou"}


def test_acquire_skips_dead_warm_pool_sandbox(tmp_path, monkeypatch):
    """验证“获取该项失效预热池沙箱”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._thread_locks = {}
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._warm_pool = {
        "sandbox-warm-dead": (
            aio_mod.SandboxInfo(
                sandbox_id="sandbox-warm-dead",
                sandbox_url="http://stale-sandbox",
                container_name="deer-flow-sandbox-sandbox-warm-dead",
            ),
            0.0,
        )
    }
    provider._config = {"replicas": 3}
    provider._backend = SimpleNamespace(
        is_alive=MagicMock(return_value=False),
        destroy=MagicMock(),
        discover=MagicMock(return_value=None),
        create=MagicMock(
            return_value=aio_mod.SandboxInfo(
                sandbox_id="sandbox-warm-dead",
                sandbox_url="http://fresh-sandbox",
                container_name="deer-flow-sandbox-sandbox-warm-dead",
            )
        ),
    )

    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_sandbox_id_for_thread", lambda _self, _thread_id, _user_id: "sandbox-warm-dead")
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_get_extra_mounts", lambda _self, _thread_id, *, user_id=None: [])
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: None)
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, timeout=60: True)

    sandbox_id = provider.acquire("thread-warm-dead", user_id="default")

    assert sandbox_id == "sandbox-warm-dead"
    provider._backend.destroy.assert_called_once()
    provider._backend.create.assert_called_once()
    assert provider._warm_pool == {}
    assert provider._thread_sandboxes[("default", "thread-warm-dead")] == "sandbox-warm-dead"
    assert provider._sandboxes["sandbox-warm-dead"].base_url == "http://fresh-sandbox"


def test_destroy_swallows_close_errors_and_still_destroys_backend(tmp_path, caplog):
    """验证“该项该项该项该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-dest-err")
    sandbox.close.side_effect = RuntimeError("boom")

    with caplog.at_level("WARNING"):
        provider.destroy("sandbox-dest-err")

    assert "Error closing sandbox sandbox-dest-err during destroy" in caplog.text
    provider._backend.destroy.assert_called_once()


def test_cleanup_idle_sandboxes_keeps_active_cleanup_and_delegates_warm_expiry(tmp_path):
    """验证“清理该项该项保留活动清理该项该项预热有效期”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._sandboxes = {"active-old": MagicMock()}
    provider._sandbox_infos = {
        "active-old": aio_mod.SandboxInfo(sandbox_id="active-old", sandbox_url="http://active-old"),
    }
    provider._thread_sandboxes = {("default", "thread-old"): "active-old"}
    provider._last_activity = {"active-old": 0.0}
    provider._warm_pool = {
        "warm-old": (
            aio_mod.SandboxInfo(sandbox_id="warm-old", sandbox_url="http://warm-old"),
            0.0,
        )
    }

    calls = []
    provider.destroy = MagicMock(side_effect=lambda _sandbox_id: calls.append("active"))
    provider._reap_expired_warm = MagicMock(side_effect=lambda _idle_timeout: calls.append("warm"))

    provider._cleanup_idle_sandboxes(1.0)

    provider.destroy.assert_called_once_with("active-old")
    provider._reap_expired_warm.assert_called_once_with(1.0)
    assert calls == ["active", "warm"]


def test_create_sandbox_evicts_oldest_warm_replica_via_shared_lifecycle(tmp_path, monkeypatch):
    """验证“创建沙箱该项该项预热该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._config = {"replicas": 2}
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}

    oldest_info = aio_mod.SandboxInfo(sandbox_id="warm-oldest", sandbox_url="http://warm-oldest")
    newest_info = aio_mod.SandboxInfo(sandbox_id="warm-newest", sandbox_url="http://warm-newest")
    created_info = aio_mod.SandboxInfo(sandbox_id="created", sandbox_url="http://created")
    provider._warm_pool = {
        "warm-newest": (newest_info, 20.0),
        "warm-oldest": (oldest_info, 10.0),
    }
    provider._backend = SimpleNamespace(
        create=MagicMock(return_value=created_info),
        destroy=MagicMock(),
    )
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_get_extra_mounts", lambda _self, _thread_id, *, user_id=None: [])
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, *, timeout=60: True)

    sandbox_id = provider._create_sandbox(None, "created", user_id="default")

    assert sandbox_id == "created"
    provider._backend.destroy.assert_called_once_with(oldest_info)
    assert "warm-oldest" not in provider._warm_pool
    assert provider._warm_pool == {"warm-newest": (newest_info, 20.0)}
    assert provider._sandbox_infos["created"] is created_info
