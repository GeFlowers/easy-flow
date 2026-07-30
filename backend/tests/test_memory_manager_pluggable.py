"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory import (
    MemoryManager,
    get_memory_manager,
    reset_memory_manager,
)
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.noop.noop_manager import NoopMemoryManager
from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config


@pytest.fixture(autouse=True)
def _isolate_memory_manager():
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    orig = get_memory_config()
    reset_memory_manager()
    yield
    set_memory_config(orig)
    reset_memory_manager()


@pytest.mark.parametrize(
    "manager_class, expected",
    [
        ("deermem", DeerMem),
        ("noop", NoopMemoryManager),
        ("deerflow.agents.memory.backends.deermem.deer_mem.DeerMem", DeerMem),
        ("deerflow.agents.memory.backends.deermem.deer_mem:DeerMem", DeerMem),
        ("deerflow.agents.memory.backends.noop.noop_manager.NoopMemoryManager", NoopMemoryManager),
        ("deerflow.agents.memory.backends.noop.noop_manager:NoopMemoryManager", NoopMemoryManager),
    ],
)
def test_resolves_configured_backend(manager_class: str, expected: type[MemoryManager]) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    set_memory_config(MemoryConfig(manager_class=manager_class))
    manager = get_memory_manager()
    assert isinstance(manager, expected)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert get_memory_manager() is manager


def test_unknown_backend_raises_instead_of_falling_back() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    set_memory_config(MemoryConfig(manager_class="bogus-backend"))
    with pytest.raises(ValueError, match="bogus-backend"):
        get_memory_manager()


def test_noop_runs_with_empty_memory() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    set_memory_config(MemoryConfig(manager_class="noop"))
    manager = get_memory_manager()
    assert manager.get_context(user_id="u") == ""
    assert manager.search("anything") == []
    assert manager.get_memory(user_id="u") == {"facts": []}
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    manager.add("t", [], agent_name=None, user_id="u")
    manager.add_nowait("t", [], agent_name=None, user_id="u")
    assert manager.get_memory(user_id="u") == {"facts": []}


def test_internal_capabilities_are_hasattr_probeable() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    set_memory_config(MemoryConfig(manager_class="deermem"))
    deermem = get_memory_manager()
    for cap in ("warm", "reload_memory", "create_fact", "delete_fact", "update_fact"):
        assert hasattr(deermem, cap), cap

    reset_memory_manager()
    set_memory_config(MemoryConfig(manager_class="noop"))
    noop = get_memory_manager()
    for cap in ("warm", "reload_memory", "create_fact", "delete_fact", "update_fact"):
        assert not hasattr(noop, cap), cap


def test_deermem_search_works_delete_export_are_stubs() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    set_memory_config(MemoryConfig(manager_class="deermem"))
    deermem = get_memory_manager()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert isinstance(deermem.search("q", user_id="u"), list)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    with pytest.raises(NotImplementedError):
        deermem.delete_memory(user_id="u")
    with pytest.raises(NotImplementedError):
        deermem.export_memory(user_id="u")


def test_factory_raises_when_storage_path_is_existing_file(tmp_path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    file_path = tmp_path / "mem.json"
    file_path.write_text("{}", encoding="utf-8")
    set_memory_config(MemoryConfig(manager_class="deermem", backend_config={"storage_path": str(file_path)}))
    with pytest.raises(ValueError, match="existing file"):
        get_memory_manager()


def test_migration_drops_file_style_legacy_storage_path(caplog) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.config.memory_config import load_memory_config_from_dict

    with caplog.at_level("WARNING", logger="deerflow.config.memory_config"):
        load_memory_config_from_dict({"storage_path": "memory.json", "max_facts": 50})
    cfg = get_memory_config()
    assert "storage_path" not in cfg.backend_config  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert cfg.backend_config.get("max_facts") == 50  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert any("looks like a file path" in r.message for r in caplog.records)


def test_empty_storage_path_factory_injects_runtime_home(tmp_path, monkeypatch) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import deerflow.config.runtime_paths as rp

    monkeypatch.setattr(rp, "runtime_home", lambda: tmp_path)
    set_memory_config(MemoryConfig(manager_class="deermem"))  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    manager = get_memory_manager()
    assert Path(manager._config.storage_path) == tmp_path
    manager.create_fact("hello", user_id="u1")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    user_dirs = [p.name for p in (tmp_path / "users").iterdir() if p.is_dir()]
    assert len(user_dirs) == 1


def test_shutdown_flush_is_on_abc_and_noop_is_noop_success() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    assert "shutdown_flush" in MemoryManager.__abstractmethods__
    reset_memory_manager()
    set_memory_config(MemoryConfig(manager_class="noop"))
    noop = get_memory_manager()
    assert noop.shutdown_flush(1.0) is True
    reset_memory_manager()


def test_deermem_shutdown_flush_delegates_to_queue_flush_sync() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    reset_memory_manager()
    set_memory_config(MemoryConfig(manager_class="deermem"))
    deermem = get_memory_manager()
    with patch.object(deermem._queue, "flush_sync", return_value=True) as spy:
        assert deermem.shutdown_flush(7.0) is True
        spy.assert_called_once_with(7.0)
    reset_memory_manager()


def test_deermem_shutdown_flush_drains_a_pending_update() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.agents.memory.backends.deermem.deermem.core.queue import ConversationContext

    reset_memory_manager()
    set_memory_config(MemoryConfig(manager_class="deermem"))
    deermem = get_memory_manager()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    deermem._queue._updater = mock_updater
    deermem._queue._queue = [ConversationContext(thread_id=f"t{i}", messages=["m"], agent_name="lead_agent") for i in range(3)]
    assert deermem.shutdown_flush(5.0) is True
    assert deermem._queue.pending_count == 0
    assert mock_updater.update_memory.call_count == 3
    reset_memory_manager()
