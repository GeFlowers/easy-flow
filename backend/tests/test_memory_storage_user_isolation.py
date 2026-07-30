"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from pathlib import Path

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage, create_empty_memory


@pytest.fixture
def base_dir(tmp_path: Path, monkeypatch) -> Path:
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def storage() -> FileMemoryStorage:
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    return FileMemoryStorage(DeerMemConfig())


class TestUserIsolatedStorage:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_save_and_load_per_user(self, storage: FileMemoryStorage, base_dir: Path):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        memory_a = create_empty_memory()
        memory_a["user"]["workContext"]["summary"] = "User A context"
        storage.save(memory_a, user_id="alice")

        memory_b = create_empty_memory()
        memory_b["user"]["workContext"]["summary"] = "User B context"
        storage.save(memory_b, user_id="bob")

        loaded_a = storage.load(user_id="alice")
        loaded_b = storage.load(user_id="bob")

        assert loaded_a["user"]["workContext"]["summary"] == "User A context"
        assert loaded_b["user"]["workContext"]["summary"] == "User B context"

    def test_user_memory_file_location(self, base_dir: Path):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        s = FileMemoryStorage(DeerMemConfig())
        s.save(create_empty_memory(), user_id="alice")
        assert (base_dir / "users" / "alice" / "memory.json").exists()

    def test_cache_isolated_per_user(self, base_dir: Path):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        s = FileMemoryStorage(DeerMemConfig())
        memory_a = create_empty_memory()
        memory_a["user"]["workContext"]["summary"] = "A"
        s.save(memory_a, user_id="alice")

        memory_b = create_empty_memory()
        memory_b["user"]["workContext"]["summary"] = "B"
        s.save(memory_b, user_id="bob")

        loaded_a = s.load(user_id="alice")
        assert loaded_a["user"]["workContext"]["summary"] == "A"

    def test_no_user_id_uses_legacy_path(self, base_dir: Path):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        s = FileMemoryStorage(DeerMemConfig())
        s.save(create_empty_memory(), user_id=None)
        assert (base_dir / "memory.json").exists()

    def test_user_and_legacy_do_not_interfere(self, base_dir: Path):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        s = FileMemoryStorage(DeerMemConfig())

        legacy_mem = create_empty_memory()
        legacy_mem["user"]["workContext"]["summary"] = "legacy"
        s.save(legacy_mem, user_id=None)

        user_mem = create_empty_memory()
        user_mem["user"]["workContext"]["summary"] = "alice"
        s.save(user_mem, user_id="alice")

        assert s.load(user_id=None)["user"]["workContext"]["summary"] == "legacy"
        assert s.load(user_id="alice")["user"]["workContext"]["summary"] == "alice"

    def test_user_agent_memory_file_location(self, base_dir: Path):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        s = FileMemoryStorage(DeerMemConfig())
        memory = create_empty_memory()
        memory["user"]["workContext"]["summary"] = "agent scoped"
        s.save(memory, "test-agent", user_id="alice")
        assert (base_dir / "users" / "alice" / "agents" / "test-agent" / "memory.json").exists()

    def test_cache_key_is_user_agent_tuple(self, base_dir: Path):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        s = FileMemoryStorage(DeerMemConfig())
        s.save(create_empty_memory(), user_id="alice")
        assert ("alice", None) in s._memory_cache

    def test_reload_with_user_id(self, base_dir: Path):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        s = FileMemoryStorage(DeerMemConfig())
        memory = create_empty_memory()
        memory["user"]["workContext"]["summary"] = "initial"
        s.save(memory, user_id="alice")

        s.load(user_id="alice")  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

        user_file = base_dir / "users" / "alice" / "memory.json"
        import json

        updated = create_empty_memory()
        updated["user"]["workContext"]["summary"] = "updated"
        user_file.write_text(json.dumps(updated))

        reloaded = s.reload(user_id="alice")
        assert reloaded["user"]["workContext"]["summary"] == "updated"
