'未说明'

import threading
import time
from pathlib import Path

import deerflow.skills.storage as skill_storage
from deerflow.config.paths import Paths
from deerflow.skills.storage import SkillStorage


class SlowSkillStorage(SkillStorage):
    '未说明'

    instances_created = 0
    instances_lock = threading.Lock()

    def __init__(self, **kwargs) -> None:
        '未说明'
        super().__init__(container_path=kwargs.get("container_path", "/mnt/skills"))
        time.sleep(0.05)
        with self.instances_lock:
            type(self).instances_created += 1

    def get_skills_root_path(self) -> Path:
        """处理获取 路径相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return Path("/tmp/skills")

    def _iter_skill_files(self):
        '未说明'
        return []

    def read_custom_skill(self, name: str) -> str:
        """处理读取 技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return ""

    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        """处理写入 技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        pass

    async def ainstall_skill_from_archive(self, archive_path) -> dict:
        """处理技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return {}

    def delete_custom_skill(self, name: str, *, history_meta: dict | None = None) -> None:
        """处理技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        pass

    def custom_skill_exists(self, name: str) -> bool:
        """处理技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return False

    def public_skill_exists(self, name: str) -> bool:
        """处理公开 技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return False

    def append_history(self, name: str, record: dict) -> None:
        '未说明'
        pass

    def read_history(self, name: str) -> list[dict]:
        """处理读取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return []


class _SkillsConfig:
    '未说明'
    use = "SlowSkillStorage"
    container_path = "/mnt/skills"

    def get_skills_path(self) -> Path:
        """处理获取 路径相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return Path("/tmp/skills")


class _AppConfig:
    '未说明'
    skills = _SkillsConfig()


# A single, stable AppConfig identity: the singleton keys its cache on the
# identity of the object returned by get_app_config(), so all threads must see
# the same instance for the singleton path to engage.
_APP_CONFIG = _AppConfig()


def _patch_storage_resolution(monkeypatch, cls=SlowSkillStorage) -> None:
    '未说明'
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _APP_CONFIG)
    monkeypatch.setattr("deerflow.reflection.resolve_class", lambda *args, **kwargs: cls)


def test_get_or_new_skill_storage_constructs_one_singleton_under_concurrent_access(monkeypatch):
    '未说明'
    skill_storage.reset_skill_storage()
    SlowSkillStorage.instances_created = 0
    _patch_storage_resolution(monkeypatch)

    n_threads = 8
    storages: list[SkillStorage] = []
    storages_lock = threading.Lock()
    # Barrier makes all threads enter get_or_new_skill_storage() at the same
    # moment, so the race is triggered deterministically rather than by chance.
    barrier = threading.Barrier(n_threads)

    def get_storage() -> None:
        """处理获取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        barrier.wait()
        storage = skill_storage.get_or_new_skill_storage()
        with storages_lock:
            storages.append(storage)

    threads = [threading.Thread(target=get_storage) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len({id(storage) for storage in storages}) == 1
        assert SlowSkillStorage.instances_created == 1
        installed = skill_storage.get_or_new_skill_storage()
        assert all(storage is installed for storage in storages)
    finally:
        skill_storage.reset_skill_storage()


def test_reset_racing_get_of_live_singleton_never_returns_none(monkeypatch):
    '未说明'
    skill_storage.reset_skill_storage()
    SlowSkillStorage.instances_created = 0
    _patch_storage_resolution(monkeypatch)

    # Populate the singleton up front so the reset races a live instance.
    skill_storage.get_or_new_skill_storage()

    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def getter() -> None:
        '未说明'
        barrier.wait()
        storage = skill_storage.get_or_new_skill_storage()
        with results_lock:
            results.append(storage)

    def resetter() -> None:
        '未说明'
        barrier.wait()
        skill_storage.reset_skill_storage()

    threads = [threading.Thread(target=getter) for _ in range(4)]
    threads.append(threading.Thread(target=resetter))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert results, "every getter recorded a result"
        assert all(isinstance(storage, SlowSkillStorage) for storage in results)
    finally:
        skill_storage.reset_skill_storage()


# ---------------------------------------------------------------------------
# Per-user skill storage lifecycle
# ---------------------------------------------------------------------------


class SlowUserSkillStorage(SkillStorage):
    '未说明'

    instances_created = 0
    instances_lock = threading.Lock()

    def __init__(self, user_id: str = "default", **kwargs) -> None:
        '未说明'
        super().__init__(container_path=kwargs.get("container_path", "/mnt/skills"))
        self._user_id = user_id
        time.sleep(0.05)
        with self.instances_lock:
            type(self).instances_created += 1

    def get_skills_root_path(self) -> Path:
        """处理获取 路径相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return Path("/tmp/skills")

    def _iter_skill_files(self):
        '未说明'
        return []

    def read_custom_skill(self, name: str) -> str:
        """处理读取 技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return ""

    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        """处理写入 技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        pass

    async def ainstall_skill_from_archive(self, archive_path) -> dict:
        """处理技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return {}

    def delete_custom_skill(self, name: str, *, history_meta: dict | None = None) -> None:
        """处理技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        pass

    def custom_skill_exists(self, name: str) -> bool:
        """处理技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return False

    def public_skill_exists(self, name: str) -> bool:
        """处理公开 技能相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return False

    def append_history(self, name: str, record: dict) -> None:
        '未说明'
        pass

    def read_history(self, name: str) -> list[dict]:
        """处理读取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return []


def _patch_user_storage_resolution(monkeypatch, cls=SlowUserSkillStorage) -> None:
    '未说明'
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _APP_CONFIG)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=Path("/tmp")))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    # get_or_new_user_skill_storage calls UserScopedSkillStorage(user_id, **kwargs)
    # directly — not via resolve_class. Patch the class reference in the module.
    monkeypatch.setattr("deerflow.skills.storage.UserScopedSkillStorage", cls)


def test_get_or_new_user_skill_storage_constructs_one_per_user_under_concurrent_access(monkeypatch):
    '未说明'
    skill_storage.reset_skill_storage()
    SlowUserSkillStorage.instances_created = 0
    _patch_user_storage_resolution(monkeypatch)

    n_threads = 8
    storages: list[SkillStorage] = []
    storages_lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def get_storage() -> None:
        """处理获取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        barrier.wait()
        storage = skill_storage.get_or_new_user_skill_storage("alice")
        with storages_lock:
            storages.append(storage)

    threads = [threading.Thread(target=get_storage) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len({id(storage) for storage in storages}) == 1
        assert SlowUserSkillStorage.instances_created == 1
    finally:
        skill_storage.reset_skill_storage()


def test_different_users_get_different_storages(monkeypatch):
    '未说明'
    skill_storage.reset_skill_storage()
    SlowUserSkillStorage.instances_created = 0
    _patch_user_storage_resolution(monkeypatch)

    s_alice = skill_storage.get_or_new_user_skill_storage("alice")
    s_bob = skill_storage.get_or_new_user_skill_storage("bob")

    try:
        assert s_alice is not s_bob
        assert s_alice._user_id == "alice"
        assert s_bob._user_id == "bob"
    finally:
        skill_storage.reset_skill_storage()


def test_reset_user_skill_storage_only_clears_target_user(monkeypatch):
    '未说明'
    skill_storage.reset_skill_storage()
    SlowUserSkillStorage.instances_created = 0
    _patch_user_storage_resolution(monkeypatch)

    s_alice = skill_storage.get_or_new_user_skill_storage("alice")
    s_bob = skill_storage.get_or_new_user_skill_storage("bob")

    skill_storage.reset_user_skill_storage("alice")

    # Alice's storage is gone
    s_alice_new = skill_storage.get_or_new_user_skill_storage("alice")
    assert s_alice_new is not s_alice

    # Bob's is still cached
    s_bob_cached = skill_storage.get_or_new_user_skill_storage("bob")
    assert s_bob_cached is s_bob


def test_reset_user_skill_storage_normalises_cache_key(monkeypatch):
    '未说明'
    from deerflow.config.paths import make_safe_user_id

    skill_storage.reset_skill_storage()
    SlowUserSkillStorage.instances_created = 0
    _patch_user_storage_resolution(monkeypatch)

    raw_id = "feishu:ou_abc123"
    safe_id = make_safe_user_id(raw_id)

    # Create storage via the normal flow (which normalises the key)
    s = skill_storage.get_or_new_user_skill_storage(raw_id)
    assert s._user_id == safe_id

    # Reset using the raw ID — must successfully clear the cache
    skill_storage.reset_user_skill_storage(raw_id)

    # A new storage should be created (old one was evicted)
    s_new = skill_storage.get_or_new_user_skill_storage(raw_id)
    assert s_new is not s
