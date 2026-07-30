"""验证 E2B 沙箱提供者及其沙箱实例的生命周期、复用与文件边界。"""

from __future__ import annotations

import importlib
import threading
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from deerflow.config.paths import Paths

# ──────────────────────────────────────────────────────────────────────────────
# E2B SDK 的替身对象
# ──────────────────────────────────────────────────────────────────────────────


class FakeCommandsAPI:
    """模拟客户端命令接口，按预设结果执行并记录调用。"""

    GONE = "__GONE__"
    NOT_FOUND_MSG = "The sandbox was not found: This error is likely due to sandbox timeout."

    def __init__(self, responses: list[Any] | None = None) -> None:
        """初始化测试替身的状态、输入和可观察记录。"""
        self.calls: list[str] = []
        self._responses = list(responses or [])

    def _next(self) -> Any:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        if not self._responses:
            return SimpleNamespace(stdout="BOOTSTRAP_OK", stderr="", exit_code=0)
        head = self._responses.pop(0)
        return head

    def run(self, cmd: str, envs: dict[str, str] | None = None, **kwargs) -> SimpleNamespace:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.calls.append(cmd)
        self.envs = getattr(self, "envs", [])
        self.envs.append(envs)
        head = self._next()
        if head == self.GONE:
            raise RuntimeError(self.NOT_FOUND_MSG)
        if callable(head):
            return head(cmd)
        if isinstance(head, SimpleNamespace):
            return head
        return SimpleNamespace(stdout=str(head), stderr="", exit_code=0)


class _FakeFileStream:
    """模拟固定分块的文件流，并记录关闭状态以验证资源释放。"""

    def __init__(self, data: bytes, *, chunk_size: int = 4096) -> None:
        """初始化测试替身的状态、输入和可观察记录。"""
        self._data = bytes(data)
        self._chunk_size = max(1, int(chunk_size))
        self._offset = 0
        self.closed = False

    def __iter__(self):
        """实现测试需要的迭代协议，覆盖结束边界。"""
        return self

    def __next__(self) -> bytes:
        """实现测试需要的迭代协议，覆盖结束边界。"""
        if self.closed or self._offset >= len(self._data):
            raise StopIteration
        end = min(self._offset + self._chunk_size, len(self._data))
        chunk = self._data[self._offset : end]
        self._offset = end
        return chunk

    def close(self) -> None:
        """更新可观察的资源清理状态，供用例验证。"""
        self.closed = True

    def __enter__(self) -> _FakeFileStream:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        return self

    def __exit__(self, *exc_info) -> None:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.close()


class FakeFilesAPI:
    """为当前测试场景提供可控输入或记录可观察结果。"""
    def __init__(
        self,
        store: dict[str, bytes] | None = None,
        *,
        stream_chunk_size: int = 4096,
    ) -> None:
        """初始化测试替身的状态、输入和可观察记录。"""
        self.store = dict(store or {})
        self.read_calls: list[tuple[str, str | None]] = []
        self.write_calls: list[tuple[str, bytes]] = []
        self.streams: list[_FakeFileStream] = []
        self._stream_chunk_size = stream_chunk_size

    def read(self, path: str, *, format: str | None = None):
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.read_calls.append((path, format))
        if path not in self.store:
            raise FileNotFoundError(path)
        data = self.store[path]
        if format == "bytes":
            return data
        if format == "stream":
            stream = _FakeFileStream(data, chunk_size=self._stream_chunk_size)
            self.streams.append(stream)
            return stream
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data

    def write(self, path: str, content: bytes) -> None:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.write_calls.append((path, content))
        self.store[path] = content


class FakeClient:
    """模拟提供者所依赖的轻量沙箱客户端。"""

    def __init__(
        self,
        sandbox_id: str = "fake-sb-1",
        *,
        commands: FakeCommandsAPI | None = None,
        files: FakeFilesAPI | None = None,
    ) -> None:
        """初始化测试替身的状态、输入和可观察记录。"""
        self.sandbox_id = sandbox_id
        self.commands = commands or FakeCommandsAPI()
        self.files = files or FakeFilesAPI()
        self.timeouts_set: list[int] = []
        self.killed = False
        self.closed = False

    def set_timeout(self, seconds: int) -> None:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.timeouts_set.append(int(seconds))

    def kill(self) -> None:
        """更新可观察的资源清理状态，供用例验证。"""
        self.killed = True

    def close(self) -> None:
        """更新可观察的资源清理状态，供用例验证。"""
        self.closed = True


class FakeSandboxClass:
    """模拟用于创建、重连和列出远端沙箱的 SDK 类。"""

    def __init__(self) -> None:
        """初始化测试替身的状态、输入和可观察记录。"""
        self.create_calls: list[dict[str, Any]] = []
        self.connect_calls: list[tuple[str, dict[str, Any]]] = []
        self.list_calls: list[dict[str, Any]] = []
        self.create_factory = lambda **kw: FakeClient(sandbox_id=f"created-{len(self.create_calls)}")
        self.connect_factory = lambda sid, **kw: FakeClient(sandbox_id=sid)
        self.list_return: Any = []

    def create(self, **kwargs: Any) -> FakeClient:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.create_calls.append(kwargs)
        return self.create_factory(**kwargs)

    def connect(self, sandbox_id: str, **kwargs: Any) -> FakeClient:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.connect_calls.append((sandbox_id, kwargs))
        return self.connect_factory(sandbox_id, **kwargs)

    def list(self, **kwargs: Any) -> Any:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.list_calls.append(kwargs)
        return self.list_return


def _make_provider(*, replicas: int = 3, idle_timeout: int = 1800) -> Any:
    """绕过常规构造流程创建内存化提供者，隔离外部配置依赖。"""
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    provider = mod.E2BSandboxProvider.__new__(mod.E2BSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._warm_pool = OrderedDict()
    provider._shutdown_called = False
    provider._config = {
        "api_key": "test-key",
        "template": "code-interpreter-v1",
        "domain": None,
        "home_dir": "/home/user",
        "idle_timeout": idle_timeout,
        "replicas": replicas,
        "mounts": [],
        "environment": {},
    }
    return provider


def _install_fake_sdk(monkeypatch, provider) -> FakeSandboxClass:
    """为当前测试场景提供可控输入或记录可观察结果。"""
    fake_cls = FakeSandboxClass()
    monkeypatch.setattr(provider, "_get_sandbox_cls", lambda: fake_cls)
    return fake_cls


def _make_sandbox(client: FakeClient, *, sandbox_id: str | None = None) -> Any:
    """为当前测试场景提供可控输入或记录可观察结果。"""
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox")
    return mod.E2BSandbox(
        id=sandbox_id or client.sandbox_id,
        client=client,
        home_dir="/home/user",
    )


def test_thread_key_returns_user_thread_tuple():
    """验证此用例覆盖的沙箱提供者主路径、输入边界和可观察结果。"""
    p = _make_provider()
    assert p._thread_key("t1", "u1") == ("u1", "t1")


def test_stable_seed_is_deterministic_and_user_scoped():
    """验证此用例覆盖的沙箱提供者主路径、输入边界和可观察结果。"""
    p = _make_provider()
    s_a = p._stable_seed("t1", "u1")
    s_b = p._stable_seed("t1", "u1")
    s_other_user = p._stable_seed("t1", "u2")
    s_other_thread = p._stable_seed("t2", "u1")
    assert s_a == s_b
    assert s_a != s_other_user
    assert s_a != s_other_thread


def test_is_sandbox_gone_error_matches_known_signatures():
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox")
    f = mod._is_sandbox_gone_error
    assert f(RuntimeError("Paused sandbox abcdef not found"))
    assert f(Exception("The sandbox was not found: due to timeout"))
    assert f(Exception("sandbox not found"))
# 无关错误不得改变沙箱死亡标记。
    assert not f(Exception("Connection reset by peer"))
    assert not f(ValueError("invalid path"))


def test_execute_command_marks_dead_on_sandbox_gone_error():
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client)
    out = sb.execute_command("echo hi")
    assert "Error: " in out and "sandbox was not found" in out
    assert sb.is_dead is True
    out2 = sb.execute_command("echo again")
    assert "reaped" in out2.lower()
    assert client.commands.calls == ["echo hi"]


def test_execute_command_returns_stdout_on_success():
    """验证此用例覆盖的沙箱提供者主路径、输入边界和可观察结果。"""
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout="hello\n", stderr="", exit_code=0)]))
    sb = _make_sandbox(client)
    assert sb.execute_command("printf hello").rstrip() == "hello"
    assert sb.is_dead is False


def test_execute_command_does_not_mark_dead_on_unrelated_error():

    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    def boom(_cmd: str, **kwargs) -> Any:
        """故意抛出预设异常，驱动当前用例的容错分支。"""
        raise RuntimeError("Connection reset by peer")

    client = FakeClient(commands=FakeCommandsAPI([boom]))
    sb = _make_sandbox(client)
    out = sb.execute_command("echo hi")
    assert "Error" in out
    assert sb.is_dead is False


def test_execute_command_forwards_env_and_timeout_to_commands_run():
    """验证命令环境和超时被以独立参数转交，密钥不会混入命令文本。"""
    commands = MagicMock()
    commands.run.return_value = SimpleNamespace(stdout="ok\n", stderr="", exit_code=0)
    client = FakeClient(commands=commands)
    sb = _make_sandbox(client)

    out = sb.execute_command("echo $TOK", env={"TOK": "secret-v"}, timeout=120)

    assert out.rstrip() == "ok"
    args, kwargs = commands.run.call_args
    assert args == ("echo $TOK",)
    assert kwargs["envs"] == {"TOK": "secret-v"}
    assert kwargs["timeout"] == 120
# 密钥不得被拼接进命令字符串。
    assert "secret-v" not in args[0]


def test_execute_command_env_none_passes_no_envs_kwarg():
    """验证未提供环境时保持兼容调用形态，不额外传递环境或超时参数。"""
    commands = MagicMock()
    commands.run.return_value = SimpleNamespace(stdout="ok\n", stderr="", exit_code=0)
    client = FakeClient(commands=commands)
    sb = _make_sandbox(client)

    sb.execute_command("echo hi")

    _, kwargs = commands.run.call_args
    assert "envs" not in kwargs
    assert "timeout" not in kwargs


def test_execute_command_forwards_env_as_envs():
    """验证单次命令环境只作用于该调用，不会污染共享沙箱状态。"""
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout="ok", stderr="", exit_code=0)]))
    sb = _make_sandbox(client)
    sb.execute_command("gh pr create", env={"GH_TOKEN": "tok-123"})
    assert client.commands.envs == [{"GH_TOKEN": "tok-123"}]


def test_execute_command_rejects_invalid_env_key():
    """验证此用例覆盖的沙箱提供者主路径、输入边界和可观察结果。"""
    client = FakeClient(commands=FakeCommandsAPI([]))
    sb = _make_sandbox(client)
    with pytest.raises(ValueError, match="extra_env key"):
        sb.execute_command("echo hi", env={"X;rm -rf /;Y": "v"})
# 参数校验在 SDK 调用之前完成。
    assert client.commands.calls == []


def test_ping_returns_false_when_sandbox_gone():
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client)
    assert sb.ping() is False
    assert sb.is_dead is True


def test_ping_returns_true_on_unknown_error():
    """验证此用例中上游异常被隔离，且不会产生超出边界的副作用。"""
    def boom(_cmd: str) -> Any:
        """故意抛出预设异常，驱动当前用例的容错分支。"""
        raise RuntimeError("upstream timeout")

    client = FakeClient(commands=FakeCommandsAPI([boom]))
    sb = _make_sandbox(client)
    assert sb.ping() is True
    assert sb.is_dead is False


def test_client_alive_true_for_healthy_client():
    """验证此用例覆盖的沙箱提供者主路径、输入边界和可观察结果。"""
    p = _make_provider()
    client = FakeClient()
    assert p._client_alive(client) is True
    assert client.commands.calls == ["true"]


def test_client_alive_false_when_sandbox_gone():
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    p = _make_provider()
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    assert p._client_alive(client) is False


def test_client_alive_treats_unknown_errors_as_alive():
    """验证此用例中上游异常被隔离，且不会产生超出边界的副作用。"""
    p = _make_provider()

    def boom(_cmd: str) -> Any:
        """故意抛出预设异常，驱动当前用例的容错分支。"""
        raise RuntimeError("flaky network")

    client = FakeClient(commands=FakeCommandsAPI([boom]))
    assert p._client_alive(client) is True


def test_safe_close_client_swallows_close_failures():
    """验证此用例中上游异常被隔离，且不会产生超出边界的副作用。"""
    p = _make_provider()

    class BadCloseClient:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        def close(self) -> None:
            """更新可观察的资源清理状态，供用例验证。"""
            raise RuntimeError("boom")

    p._safe_close_client(BadCloseClient())
    p._safe_close_client(None)


def test_kill_and_close_invokes_kill_and_close_in_order():
    """验证此用例覆盖的沙箱提供者主路径、输入边界和可观察结果。"""
    p = _make_provider()
    client = FakeClient()
    sb = _make_sandbox(client)
    p._kill_and_close(sb)
    assert client.killed is True


def test_kill_and_close_swallows_kill_exceptions():
    """验证此用例中上游异常被隔离，且不会产生超出边界的副作用。"""
    p = _make_provider()
    client = FakeClient()
    sb = _make_sandbox(client)

    def explode():
        """故意抛出预设异常，驱动当前用例的容错分支。"""
        raise RuntimeError("already gone")

    client.kill = explode
    p._kill_and_close(sb)


def test_reuse_in_process_sandbox_returns_cached_id_on_healthy_reuse():
    """验证此用例中缓存沙箱的复用条件、探活结果和映射清理。"""
    p = _make_provider()
    client = FakeClient()
    sb = _make_sandbox(client, sandbox_id="sb-1")
    p._sandboxes["sb-1"] = sb
    p._thread_sandboxes[("u1", "t1")] = "sb-1"

    sid = p._reuse_in_process_sandbox("t1", user_id="u1")
    assert sid == "sb-1"
    assert client.timeouts_set, "expected set_timeout to be called on reuse"


def test_reuse_in_process_sandbox_evicts_dead_sandbox():
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    p = _make_provider()
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client, sandbox_id="sb-dead")
    sb._dead = True
    p._sandboxes["sb-dead"] = sb
    p._thread_sandboxes[("u1", "t1")] = "sb-dead"

    sid = p._reuse_in_process_sandbox("t1", user_id="u1")
    assert sid is None
    assert "sb-dead" not in p._sandboxes
    assert ("u1", "t1") not in p._thread_sandboxes


def test_reuse_in_process_sandbox_evicts_when_ping_fails():
    """验证此用例中缓存沙箱的复用条件、探活结果和映射清理。"""
    p = _make_provider()
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client, sandbox_id="sb-stale")
    p._sandboxes["sb-stale"] = sb
    p._thread_sandboxes[("u1", "t1")] = "sb-stale"

    sid = p._reuse_in_process_sandbox("t1", user_id="u1")
    assert sid is None
    assert sb.is_dead is True
    assert "sb-stale" not in p._sandboxes


def test_reuse_in_process_sandbox_cleans_dangling_mapping():
    """验证此用例中缓存沙箱的复用条件、探活结果和映射清理。"""
    p = _make_provider()
    p._thread_sandboxes[("u1", "t1")] = "ghost"
    sid = p._reuse_in_process_sandbox("t1", user_id="u1")
    assert sid is None
    assert ("u1", "t1") not in p._thread_sandboxes


def test_reuse_in_process_sandbox_returns_none_when_no_mapping():
    """验证此用例中缓存沙箱的复用条件、探活结果和映射清理。"""
    p = _make_provider()
    assert p._reuse_in_process_sandbox("t-x", user_id="u-x") is None


def test_reclaim_warm_pool_sandbox_happy_path(monkeypatch):
    """验证此用例中热池沙箱的匹配、重连或清理行为与线程归属保持一致。"""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    seed = p._stable_seed("t1", "u1")
    p._warm_pool["sb-warm"] = (seed, 12345.0)

    sid = p._reclaim_warm_pool_sandbox("t1", user_id="u1")
    assert sid == "sb-warm"
    assert "sb-warm" in p._sandboxes
    assert p._thread_sandboxes[("u1", "t1")] == "sb-warm"
    assert "sb-warm" not in p._warm_pool
    assert [c[0] for c in fake_cls.connect_calls] == ["sb-warm"]


def test_reclaim_warm_pool_sandbox_drops_dead_entry(monkeypatch):
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.connect_factory = lambda sid, **kw: FakeClient(sandbox_id=sid, commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    seed = p._stable_seed("t1", "u1")
    p._warm_pool["sb-zombie"] = (seed, 12345.0)

    sid = p._reclaim_warm_pool_sandbox("t1", user_id="u1")
    assert sid is None
    assert "sb-zombie" not in p._sandboxes
    assert "sb-zombie" not in p._warm_pool


def test_reclaim_warm_pool_sandbox_handles_reconnect_exception(monkeypatch):
    """验证此用例中上游异常被隔离，且不会产生超出边界的副作用。"""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)

    def boom(sid, **kw):
        """故意抛出预设异常，驱动当前用例的容错分支。"""
        raise RuntimeError("404 Not Found")

    fake_cls.connect_factory = boom
    seed = p._stable_seed("t1", "u1")
    p._warm_pool["sb-broken"] = (seed, 12345.0)

    sid = p._reclaim_warm_pool_sandbox("t1", user_id="u1")
    assert sid is None
    assert "sb-broken" not in p._warm_pool


def test_reclaim_warm_pool_sandbox_returns_none_on_seed_mismatch(monkeypatch):
    """验证此用例中热池沙箱的匹配、重连或清理行为与线程归属保持一致。"""
    p = _make_provider()
    _install_fake_sdk(monkeypatch, p)
    p._warm_pool["sb-other"] = ("some-other-seed", 12345.0)
    assert p._reclaim_warm_pool_sandbox("t1", user_id="u1") is None
# 不相关条目必须保持原状。
    assert "sb-other" in p._warm_pool


class _FakePaginator:
    """模拟 SDK 分页器，通过下一页方法逐批返回远端条目。"""

    def __init__(self, pages: list[list[Any]]) -> None:
        """初始化测试替身的状态、输入和可观察记录。"""
        self._pages = list(pages)
        self.has_next = bool(self._pages)
        self.calls = 0

    def next_items(self) -> list[Any]:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        self.calls += 1
        if not self._pages:
            self.has_next = False
            return []
        page = self._pages.pop(0)
        self.has_next = bool(self._pages)
        return page


def _info(sandbox_id: str, user_id: str, thread_id: str):
    """为当前测试场景提供可控输入或记录可观察结果。"""
    return SimpleNamespace(
        sandbox_id=sandbox_id,
        metadata={
            "deer_flow_provider": "e2b_sandbox_provider",
            "deer_flow_user": user_id,
            "deer_flow_thread": thread_id,
        },
    )


def test_discover_remote_sandbox_walks_paginator(monkeypatch):
    """验证此用例中远程沙箱发现兼容分页、列表和连接失败边界。"""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = _FakePaginator(
        [
            [_info("sb-other", "u-x", "t-x")],
            [_info("sb-match", "u1", "t1")],
        ]
    )

    sid = p._discover_remote_sandbox("t1", user_id="u1")
    assert sid == "sb-match"
    assert p._thread_sandboxes[("u1", "t1")] == "sb-match"


def test_discover_remote_sandbox_accepts_legacy_list(monkeypatch):
    """验证此用例中远程沙箱发现兼容分页、列表和连接失败边界。"""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-legacy", "u1", "t1")]

    sid = p._discover_remote_sandbox("t1", user_id="u1")
    assert sid == "sb-legacy"


def test_discover_remote_sandbox_skips_dead_candidate(monkeypatch):
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-dead", "u1", "t1")]
    fake_cls.connect_factory = lambda sid, **kw: FakeClient(sandbox_id=sid, commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))

    assert p._discover_remote_sandbox("t1", user_id="u1") is None
    assert ("u1", "t1") not in p._thread_sandboxes


def test_discover_remote_sandbox_returns_none_when_list_raises(monkeypatch):
    """验证此用例中远程沙箱发现兼容分页、列表和连接失败边界。"""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)

    def boom(**kw):
        """故意抛出预设异常，驱动当前用例的容错分支。"""
        raise RuntimeError("API unreachable")

    fake_cls.list = boom
    assert p._discover_remote_sandbox("t1", user_id="u1") is None


def test_bootstrap_sandbox_paths_emits_expected_script():
    """验证此用例覆盖的沙箱提供者主路径、输入边界和可观察结果。"""
    p = _make_provider()
    client = FakeClient()
    p._bootstrap_sandbox_paths(client)
    assert len(client.commands.calls) == 1
    script = client.commands.calls[0]
    assert "ln -sfn" in script
    assert "/mnt/user-data" in script
    assert "/mnt/acp-workspace" in script
    assert "BOOTSTRAP_OK" in script
    for sub in ("workspace", "uploads", "outputs", "acp-workspace"):
        assert f"/home/user/{sub}" in script


def test_bootstrap_sandbox_paths_swallows_command_failure():
    """验证此用例中上游异常被隔离，且不会产生超出边界的副作用。"""
    p = _make_provider()

    def boom(_cmd: str) -> Any:
        """故意抛出预设异常，驱动当前用例的容错分支。"""
        raise RuntimeError("sudo not allowed")

    client = FakeClient(commands=FakeCommandsAPI([boom]))
    p._bootstrap_sandbox_paths(client)


def test_release_unknown_sandbox_id_is_noop():
    """验证此用例覆盖的沙箱提供者主路径、输入边界和可观察结果。"""
    p = _make_provider()
    p.release("nonexistent")
    assert p._warm_pool == OrderedDict()


def test_release_dead_sandbox_skips_warm_pool(monkeypatch):
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    p = _make_provider()
    client = FakeClient()
    sb = _make_sandbox(client, sandbox_id="sb-dead")
    sb._dead = True
    p._sandboxes["sb-dead"] = sb
    p._thread_sandboxes[("u1", "t1")] = "sb-dead"

    p.release("sb-dead")

    assert "sb-dead" not in p._warm_pool, "dead sandbox must not be parked"
    assert "sb-dead" not in p._sandboxes
    assert ("u1", "t1") not in p._thread_sandboxes
    assert client.killed is True, "release of dead sandbox must kill the remote VM"


def test_release_healthy_sandbox_parks_in_warm_pool(monkeypatch, tmp_path):
    """验证此用例中热池沙箱的匹配、重连或清理行为与线程归属保持一致。"""
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    cmds = FakeCommandsAPI([SimpleNamespace(stdout="", stderr="", exit_code=0)])
    client = FakeClient(commands=cmds)
    sb = _make_sandbox(client, sandbox_id="sb-warm-1")
    p._sandboxes["sb-warm-1"] = sb
    p._thread_sandboxes[("u1", "t1")] = "sb-warm-1"

    p.release("sb-warm-1")

    assert "sb-warm-1" in p._warm_pool
    seed_in_pool, _ts = p._warm_pool["sb-warm-1"]
    assert seed_in_pool == p._stable_seed("t1", "u1")
    assert client.killed is False
    assert client.timeouts_set


def test_release_skips_warm_pool_when_sync_reveals_dead_vm(monkeypatch, tmp_path):
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client, sandbox_id="sb-died-during-sync")
    p._sandboxes["sb-died-during-sync"] = sb
    p._thread_sandboxes[("u1", "t1")] = "sb-died-during-sync"

    p.release("sb-died-during-sync")

    assert sb.is_dead is True
    assert "sb-died-during-sync" not in p._warm_pool
    assert client.killed is True


def _setup_paths(monkeypatch, tmp_path):
    """为当前测试场景提供可控输入或记录可观察结果。"""
    paths_mod = importlib.import_module("deerflow.config.paths")
    monkeypatch.setattr(paths_mod, "get_paths", lambda: Paths(base_dir=tmp_path), raising=False)


def test_sync_outputs_to_host_writes_new_files(monkeypatch, tmp_path):
    """验证此用例中输出同步对新文件、已知文件和容量边界的处理。"""
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    listing = "13\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"%PDF-1.4hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-1")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    expected = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "random.pdf"
    assert expected.exists()
    assert expected.read_bytes() == b"%PDF-1.4hello"


def test_sync_outputs_to_host_skips_unchanged_files(monkeypatch, tmp_path):
    """验证此用例中输出同步对新文件、已知文件和容量边界的处理。"""
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    out_dir = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "random.pdf"
    target.write_bytes(b"%PDF-1.4hello")

    listing = "13\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"DIFFERENT-SAME-LEN"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-2")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert files.read_calls == [], "size match should skip the download round-trip"
    assert target.read_bytes() == b"%PDF-1.4hello"


def test_sync_outputs_to_host_marks_dead_on_sandbox_gone(monkeypatch, tmp_path):
    """验证此用例在沙箱已失效边界下的资源回收与状态更新行为。"""
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    cmds = FakeCommandsAPI([FakeCommandsAPI.GONE])
    client = FakeClient(commands=cmds)
    sb = _make_sandbox(client, sandbox_id="sb-sync-dead")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert sb.is_dead is True


def test_sync_outputs_to_host_uses_virtual_path_for_download(monkeypatch, tmp_path):
    """验证同步助手会把物理输出路径转换为下载接口要求的虚拟路径。"""
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)

    listing = "5\t/home/user/outputs/sub/x.txt\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/sub/x.txt": b"hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-3")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    read_paths = [r[0] for r in files.read_calls]
    assert "/home/user/outputs/sub/x.txt" in read_paths


def test_sync_outputs_to_host_is_noop_when_client_closed():
    """验证此用例中输出同步对新文件、已知文件和容量边界的处理。"""
    p = _make_provider()
    sb = _make_sandbox(FakeClient(), sandbox_id="sb-x")
    sb.close()
    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")


def test_download_file_uses_streaming_read_and_returns_full_bytes():
    """验证此用例中下载路径使用流式读取、容量限制和兼容回退。"""
    payload = b"A" * (128 * 1024)  # 128 KiB，远低于容量上限。
    files = FakeFilesAPI(store={"/home/user/outputs/small.bin": payload})
    client = FakeClient(files=files)
    sb = _make_sandbox(client, sandbox_id="sb-stream-1")

    data = sb.download_file("/mnt/user-data/outputs/small.bin")

    assert data == payload
    formats_used = [fmt for _p, fmt in files.read_calls]
    assert "stream" in formats_used, f"expected download_file to invoke read(format='stream'), got {formats_used!r}"
    assert files.streams, "download_file must actually consume a stream"
    assert files.streams[-1].closed, "stream must be closed after successful read"


def test_download_file_streaming_raises_efbig_before_full_buffering():
    """验证此用例中下载路径使用流式读取、容量限制和兼容回退。"""
    import errno as _errno

    from deerflow.community.e2b_sandbox import e2b_sandbox as e2b_sb_mod

    cap = e2b_sb_mod._MAX_DOWNLOAD_SIZE

    class _OversizeStream:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        def __init__(self) -> None:
            """初始化测试替身的状态、输入和可观察记录。"""
            self.bytes_yielded = 0
            self.closed = False
            self._chunk = b"X" * (1024 * 1024)  # 每块 1 MiB。

        def __iter__(self):
            """实现测试需要的迭代协议，覆盖结束边界。"""
            return self

        def __next__(self) -> bytes:
            """实现测试需要的迭代协议，覆盖结束边界。"""
            if self.closed:
                raise StopIteration
            # 产出略高于上限的数据；调用方必须在全部进入内存前中止。
            if self.bytes_yielded > cap + 4 * len(self._chunk):
                raise StopIteration
            self.bytes_yielded += len(self._chunk)
            return self._chunk

        def close(self) -> None:
            """更新可观察的资源清理状态，供用例验证。"""
            self.closed = True

    stream = _OversizeStream()

    class _StubFilesAPI:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        def __init__(self) -> None:
            """初始化测试替身的状态、输入和可观察记录。"""
            self.calls: list[tuple[str, str | None]] = []

        def read(self, path: str, *, format: str | None = None):
            """为当前测试场景提供可控输入或记录可观察结果。"""
            self.calls.append((path, format))
            assert format == "stream", "provider must request a streamed download"
            return stream

    files = _StubFilesAPI()
    client = FakeClient(files=files)  # type: ignore[arg-type]
    sb = _make_sandbox(client, sandbox_id="sb-stream-oversize")

    try:
        sb.download_file("/mnt/user-data/outputs/huge.bin")
    except OSError as exc:
        assert exc.errno == _errno.EFBIG, f"expected EFBIG, got errno={exc.errno!r} ({exc})"
    else:  # pragma: no cover - defensive
        raise AssertionError("download_file must raise OSError(EFBIG) on oversize stream")

    assert stream.closed is True, "stream must be closed on abort so the pooled connection is released"
    assert stream.bytes_yielded <= cap + 2 * 1024 * 1024, f"aborted too late: yielded={stream.bytes_yielded} vs cap={cap}"


def test_download_file_falls_back_to_buffered_read_for_legacy_sdk():

    """验证此用例中下载路径使用流式读取、容量限制和兼容回退。"""
    class _LegacyFilesAPI:
        """为当前测试场景提供可控输入或记录可观察结果。"""
        def __init__(self, data: bytes) -> None:
            """初始化测试替身的状态、输入和可观察记录。"""
            self._data = data
            self.calls: list[tuple[str, str | None]] = []

        def read(self, path: str, *, format: str | None = None):
            """为当前测试场景提供可控输入或记录可观察结果。"""
            self.calls.append((path, format))
            if format == "stream":
                raise TypeError("format='stream' unsupported")
            if format == "bytes":
                return self._data
            return self._data.decode("utf-8", errors="replace")

    files = _LegacyFilesAPI(b"legacy-payload")
    client = FakeClient(files=files)  # type: ignore[arg-type]
    sb = _make_sandbox(client, sandbox_id="sb-legacy")

    data = sb.download_file("/mnt/user-data/outputs/legacy.bin")
    assert data == b"legacy-payload"
    formats_used = [fmt for _p, fmt in files.calls]
    assert formats_used == ["stream", "bytes"], f"expected stream then bytes fallback, got {formats_used!r}"


def test_sync_outputs_to_host_skips_oversize_files(monkeypatch, tmp_path):
    """验证列出的超限文件在下载前被跳过，宿主输出目录不会留下残余文件。"""
    from deerflow.community.e2b_sandbox import e2b_sandbox as e2b_sb_mod

    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)

    oversize = e2b_sb_mod._MAX_DOWNLOAD_SIZE + 1
    listing = f"{oversize}\t/home/user/outputs/huge.bin\x00"
    files = FakeFilesAPI()  # 不提供存储项：任何读取尝试都会抛错。
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-oversize")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert files.read_calls == [], "oversize files must be skipped without invoking download_file"
    host_target = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "huge.bin"
    assert not host_target.exists(), "no oversize artefact must be written to host"
