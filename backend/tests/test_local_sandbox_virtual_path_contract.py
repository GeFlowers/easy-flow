"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider


def _build_config(skills_dir: Path) -> SimpleNamespace:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return SimpleNamespace(
        skills=SimpleNamespace(
            container_path="/mnt/skills",
            get_skills_path=lambda: skills_dir,
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider", mounts=[]),
    )


@pytest.fixture
def isolated_paths(monkeypatch, tmp_path):
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    yield tmp_path
    monkeypatch.setattr(paths_module, "_paths", None)


@pytest.fixture
def provider(isolated_paths, tmp_path):
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    cfg = _build_config(skills_dir)
    with patch("deerflow.config.get_app_config", return_value=cfg):
        yield LocalSandboxProvider()


# ──────────────────────────────────────────────────────────────────────────
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ──────────────────────────────────────────────────────────────────────────


def test_acquire_with_thread_id_returns_per_thread_id(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha", user_id="default")
    assert sandbox_id == "local:default:alpha"


def test_acquire_with_thread_id_uses_uniform_user_scoped_id(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    assert provider.acquire("alpha", user_id="alice") == "local:alice:alpha"


def test_acquire_without_thread_id_remains_legacy_local_id(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    assert provider.acquire() == "local"
    assert provider.acquire(None) == "local"


def test_write_then_read_via_public_api_with_virtual_path(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    assert sbx is not None

    virtual = "/mnt/user-data/workspace/hello.txt"
    sbx.write_file(virtual, "hi there")
    assert sbx.read_file(virtual) == "hi there"


def test_list_dir_via_public_api_with_virtual_path(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.write_file("/mnt/user-data/workspace/foo.txt", "x")
    entries = sbx.list_dir("/mnt/user-data/workspace")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert any("/mnt/user-data/workspace/foo.txt" in e for e in entries)


def test_execute_command_with_virtual_path(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.write_file("/mnt/user-data/uploads/note.txt", "payload")
    output = sbx.execute_command("ls /mnt/user-data/uploads")
    assert "note.txt" in output


def test_glob_with_virtual_path(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.write_file("/mnt/user-data/outputs/report.md", "# r")
    matches, _ = sbx.glob("/mnt/user-data/outputs", "*.md")
    assert any(m.endswith("/mnt/user-data/outputs/report.md") for m in matches)


def test_grep_with_virtual_path(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.write_file("/mnt/user-data/workspace/findme.txt", "needle line\nother line")
    matches, _ = sbx.grep("/mnt/user-data/workspace", "needle", literal=True)
    assert matches
    assert matches[0].path.endswith("/mnt/user-data/workspace/findme.txt")


def test_execute_command_lists_aggregate_user_data_root(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    sbx.write_file("/mnt/user-data/workspace/.keep", "")
    sbx.write_file("/mnt/user-data/uploads/.keep", "")
    sbx.write_file("/mnt/user-data/outputs/.keep", "")
    output = sbx.execute_command("ls /mnt/user-data")
    assert "workspace" in output
    assert "uploads" in output
    assert "outputs" in output


def test_list_dir_on_user_data_root_does_not_duplicate_subdir_mounts(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    sbx.write_file("/mnt/user-data/workspace/.keep", "")
    sbx.write_file("/mnt/user-data/uploads/.keep", "")
    sbx.write_file("/mnt/user-data/outputs/.keep", "")

    entries = sbx.list_dir("/mnt/user-data")

    for subdir in ("workspace", "uploads", "outputs"):
        matches = [e for e in entries if e.rstrip("/") == f"/mnt/user-data/{subdir}"]
        assert len(matches) == 1, f"{subdir} listed {len(matches)} time(s), expected exactly 1: {entries}"


def test_update_file_with_virtual_path_for_remote_sync_scenario(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox_id = provider.acquire("alpha")
    sbx = provider.get(sandbox_id)
    sbx.update_file("/mnt/user-data/uploads/blob.bin", b"\x00\x01\x02binary")
    assert sbx.read_file("/mnt/user-data/uploads/blob.bin").startswith("\x00\x01\x02")


# ──────────────────────────────────────────────────────────────────────────
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ──────────────────────────────────────────────────────────────────────────


def test_two_threads_get_distinct_sandboxes(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sid_a = provider.acquire("alpha")
    sid_b = provider.acquire("beta")
    assert sid_a != sid_b

    sbx_a = provider.get(sid_a)
    sbx_b = provider.get(sid_b)
    assert sbx_a is not sbx_b


def test_per_thread_user_data_mapping_isolated(provider, isolated_paths):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sid_a = provider.acquire("alpha")
    sid_b = provider.acquire("beta")
    sbx_a = provider.get(sid_a)
    sbx_b = provider.get(sid_b)

    sbx_a.write_file("/mnt/user-data/workspace/secret.txt", "alpha-only")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    with pytest.raises(FileNotFoundError):
        sbx_b.read_file("/mnt/user-data/workspace/secret.txt")


def test_same_thread_different_users_are_isolated(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sid_alice = provider.acquire("alpha", user_id="alice")
    sid_bob = provider.acquire("alpha", user_id="bob")
    assert sid_alice != sid_bob

    sbx_alice = provider.get(sid_alice)
    sbx_bob = provider.get(sid_bob)
    assert sbx_alice is not sbx_bob

    sbx_alice.write_file("/mnt/user-data/outputs/report.md", "alice-only")
    with pytest.raises(FileNotFoundError):
        sbx_bob.read_file("/mnt/user-data/outputs/report.md")


def test_agent_written_paths_per_thread_isolation(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sid_a = provider.acquire("alpha")
    sid_b = provider.acquire("beta")
    sbx_a = provider.get(sid_a)
    sbx_b = provider.get(sid_b)
    sbx_a.write_file("/mnt/user-data/workspace/in-a.txt", "marker")
    assert sbx_a._agent_written_paths
    assert not sbx_b._agent_written_paths


# ──────────────────────────────────────────────────────────────────────────
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ──────────────────────────────────────────────────────────────────────────


def test_get_returns_cached_instance_for_known_id(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sid = provider.acquire("alpha")
    assert provider.get(sid) is provider.get(sid)


def test_get_unknown_id_returns_none(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    assert provider.get("local:default:nonexistent") is None


def test_release_is_noop_keeps_instance_available(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sid = provider.acquire("alpha")
    sbx_before = provider.get(sid)
    provider.release(sid)
    sbx_after = provider.get(sid)
    assert sbx_before is sbx_after


def test_reset_clears_both_generic_and_per_thread_caches(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    provider.acquire()  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    provider.acquire("alpha")  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert provider._generic_sandbox is not None
    assert provider._thread_sandboxes

    provider.reset()
    assert provider._generic_sandbox is None
    assert not provider._thread_sandboxes


# ──────────────────────────────────────────────────────────────────────────
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ──────────────────────────────────────────────────────────────────────────


def test_is_local_sandbox_accepts_generic_and_per_thread_id_formats():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.sandbox.tools import is_local_sandbox

    generic = SimpleNamespace(state={"sandbox": {"sandbox_id": "local"}}, context={})
    per_thread = SimpleNamespace(state={"sandbox": {"sandbox_id": "local:default:alpha"}}, context={})
    foreign = SimpleNamespace(state={"sandbox": {"sandbox_id": "aio-12345"}}, context={})
    unset = SimpleNamespace(state={}, context={})

    assert is_local_sandbox(generic) is True
    assert is_local_sandbox(per_thread) is True
    assert is_local_sandbox(foreign) is False
    assert is_local_sandbox(unset) is False


# ──────────────────────────────────────────────────────────────────────────
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ──────────────────────────────────────────────────────────────────────────


def test_concurrent_acquire_same_thread_yields_single_instance(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import threading
    import time

    from deerflow.sandbox.local import local_sandbox as local_sandbox_module

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    original_init = local_sandbox_module.LocalSandbox.__init__

    def slow_init(self, *args, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        time.sleep(0.05)
        original_init(self, *args, **kwargs)

    barrier = threading.Barrier(8)
    results: list[str] = []
    results_lock = threading.Lock()

    def racer():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        barrier.wait()
        sid = provider.acquire("alpha", user_id="default")
        with results_lock:
            results.append(sid)

    with patch.object(local_sandbox_module.LocalSandbox, "__init__", slow_init):
        threads = [threading.Thread(target=racer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(set(results)) == 1, f"Racers saw different ids: {results}"
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(provider._thread_sandboxes) == 1
    assert ("default", "alpha") in provider._thread_sandboxes


def test_concurrent_acquire_distinct_threads_yields_distinct_instances(provider):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import threading

    barrier = threading.Barrier(6)
    sids: dict[str, str] = {}
    lock = threading.Lock()

    def racer(name: str):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        barrier.wait()
        sid = provider.acquire(name, user_id="default")
        with lock:
            sids[name] = sid

    threads = [threading.Thread(target=racer, args=(f"t{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert set(sids.values()) == {f"local:default:t{i}" for i in range(6)}
    assert set(provider._thread_sandboxes.keys()) == {("default", f"t{i}") for i in range(6)}


# ──────────────────────────────────────────────────────────────────────────
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ──────────────────────────────────────────────────────────────────────────


def test_thread_sandbox_cache_is_bounded(isolated_paths, tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    cfg = _build_config(skills_dir)

    with patch("deerflow.config.get_app_config", return_value=cfg):
        provider = LocalSandboxProvider(max_cached_threads=3)

    for i in range(5):
        provider.acquire(f"t{i}", user_id="default")

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert set(provider._thread_sandboxes.keys()) == {("default", "t2"), ("default", "t3"), ("default", "t4")}
    assert provider.get("local:default:t0") is None
    assert provider.get("local:default:t4") is not None


def test_lru_promotes_recently_used_thread(isolated_paths, tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    cfg = _build_config(skills_dir)

    with patch("deerflow.config.get_app_config", return_value=cfg):
        provider = LocalSandboxProvider(max_cached_threads=3)

    for name in ["a", "b", "c"]:
        provider.acquire(name, user_id="default")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    provider.get("local:default:a")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    provider.acquire("d", user_id="default")

    assert ("default", "a") in provider._thread_sandboxes
    assert ("default", "b") not in provider._thread_sandboxes
    assert {("default", "a"), ("default", "c"), ("default", "d")} == set(provider._thread_sandboxes.keys())
