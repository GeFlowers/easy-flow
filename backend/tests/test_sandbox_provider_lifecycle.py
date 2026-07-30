'未说明'

import threading
import time

import deerflow.sandbox.sandbox_provider as sandbox_provider
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider


class SlowSandboxProvider(SandboxProvider):
    '未说明'

    instances_created = 0
    instances_lock = threading.Lock()

    def __init__(self) -> None:
        '未说明'
        time.sleep(0.05)
        with self.instances_lock:
            type(self).instances_created += 1

    def acquire(self, thread_id: str | None = None) -> str:
        '未说明'
        return "sandbox-id"

    def get(self, sandbox_id: str) -> Sandbox | None:
        """处理获取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None

    def release(self, sandbox_id: str) -> None:
        '未说明'
        pass


class ShutdownSandboxProvider(SlowSandboxProvider):
    '未说明'

    registry: list["ShutdownSandboxProvider"] = []
    registry_lock = threading.Lock()

    def __init__(self) -> None:
        '未说明'
        super().__init__()
        self.shutdown_calls = 0
        self.reset_calls = 0
        with self.registry_lock:
            type(self).registry.append(self)

    def shutdown(self) -> None:
        # A non-trivial teardown: the fix runs this outside the lock, so a
        # concurrent get() must not be blocked or torn by it.
        '未说明'
        time.sleep(0.02)
        self.shutdown_calls += 1

    def reset(self) -> None:
        """处理重置相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        self.reset_calls += 1


class _SandboxConfig:
    '未说明'
    use = "SlowSandboxProvider"


class _AppConfig:
    '未说明'
    sandbox = _SandboxConfig()


def _patch_provider_resolution(monkeypatch, cls=SlowSandboxProvider) -> None:
    '未说明'
    monkeypatch.setattr(sandbox_provider, "get_app_config", lambda: _AppConfig())
    monkeypatch.setattr(sandbox_provider, "resolve_class", lambda *args: cls)


def test_get_sandbox_provider_installs_one_singleton_under_concurrent_access(monkeypatch):
    '未说明'
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch)

    n_threads = 8
    providers: list[SandboxProvider] = []
    providers_lock = threading.Lock()
    # Barrier makes all threads enter get_sandbox_provider() at the same moment,
    # so the race is triggered deterministically rather than probabilistically.
    barrier = threading.Barrier(n_threads)

    def get_provider() -> None:
        """处理获取 提供方相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with providers_lock:
            providers.append(provider)

    threads = [threading.Thread(target=get_provider) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        # Every caller sees the one installed singleton, whichever candidate won.
        assert len({id(provider) for provider in providers}) == 1
        installed = sandbox_provider.get_sandbox_provider()
        assert all(p is installed for p in providers)
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_reset_racing_get_of_live_singleton_never_returns_none_or_torn(monkeypatch):
    '未说明'
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch)

    # Populate the singleton up front so the reset races a live instance.
    sandbox_provider.get_sandbox_provider()

    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def getter() -> None:
        '未说明'
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with results_lock:
            results.append(provider)

    def resetter() -> None:
        '未说明'
        barrier.wait()
        sandbox_provider.reset_sandbox_provider()

    threads = [threading.Thread(target=getter) for _ in range(4)]
    threads.append(threading.Thread(target=resetter))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        # Whatever each getter saw — the original singleton or a freshly rebuilt
        # one after the reset — it must be a real provider, never None and never
        # a partially constructed object.
        assert results, "every getter recorded a result"
        assert all(isinstance(p, SlowSandboxProvider) for p in results)
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_shutdown_racing_get_of_live_singleton_never_returns_none_or_torn(monkeypatch):
    '未说明'
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch, cls=ShutdownSandboxProvider)

    sandbox_provider.get_sandbox_provider()  # live singleton before the race

    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def getter() -> None:
        '未说明'
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with results_lock:
            results.append(provider)

    def shutter() -> None:
        '未说明'
        barrier.wait()
        sandbox_provider.shutdown_sandbox_provider()

    threads = [threading.Thread(target=getter) for _ in range(4)]
    threads.append(threading.Thread(target=shutter))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert results
        assert all(isinstance(p, ShutdownSandboxProvider) for p in results)
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_set_racing_get_never_returns_none_or_torn(monkeypatch):
    '未说明'
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch)

    sandbox_provider.get_sandbox_provider()  # live singleton before the race
    injected = SlowSandboxProvider()

    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def getter() -> None:
        '未说明'
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with results_lock:
            results.append(provider)

    def setter() -> None:
        '未说明'
        barrier.wait()
        sandbox_provider.set_sandbox_provider(injected)

    threads = [threading.Thread(target=getter) for _ in range(4)]
    threads.append(threading.Thread(target=setter))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert results
        assert all(isinstance(p, SlowSandboxProvider) for p in results)
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_losing_cold_start_racer_shuts_down_its_orphan(monkeypatch):
    '未说明'
    sandbox_provider.reset_sandbox_provider()
    ShutdownSandboxProvider.instances_created = 0
    ShutdownSandboxProvider.registry = []
    _patch_provider_resolution(monkeypatch, cls=ShutdownSandboxProvider)

    n_threads = 8
    providers: list[ShutdownSandboxProvider] = []
    providers_lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def get_provider() -> None:
        """处理获取 提供方相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with providers_lock:
            providers.append(provider)

    threads = [threading.Thread(target=get_provider) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        winner = sandbox_provider.get_sandbox_provider()
        # Exactly one instance is installed and returned to every caller.
        assert len({id(p) for p in providers}) == 1
        assert all(p is winner for p in providers)
        # The winner is never torn down...
        assert winner.shutdown_calls == 0
        # ...and every loser that was constructed had shutdown() called on it
        # exactly once.
        losers = [inst for inst in ShutdownSandboxProvider.registry if inst is not winner]
        assert len(losers) == ShutdownSandboxProvider.instances_created - 1
        assert all(inst.shutdown_calls == 1 for inst in losers)
    finally:
        sandbox_provider.reset_sandbox_provider()
