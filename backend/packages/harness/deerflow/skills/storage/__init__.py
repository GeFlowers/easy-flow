"""根据配置创建并缓存全局或按用户隔离的技能存储实例。"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow.skills.types import SkillCategory

logger = logging.getLogger(__name__)

_default_skill_storage: SkillStorage | None = None
_default_skill_storage_config: object | None = None  # AppConfig identity the singleton was built from
_skill_storage_lock = threading.Lock()

# Maximum number of per-user storage instances to keep in cache.
# Real-world deployments rarely have more than a few concurrent users per
# process; 64 is a generous ceiling that prevents unbounded memory growth.
_MAX_USER_SCOPED_STORAGES = 64

# Per-user skill storage cache with double-check lock for concurrent creation.
# OrderedDict so that LRU eviction can remove the least-recently-used entry
# via ``move_to_end`` + ``popitem(last=False)`` when the cache exceeds
# ``_MAX_USER_SCOPED_STORAGES``.
_user_scoped_storages: OrderedDict[str, UserScopedSkillStorage] = OrderedDict()
_user_scoped_storage_lock = threading.Lock()


def get_or_new_skill_storage(**kwargs) -> SkillStorage:
    """按需返回技能存储；显式路径或配置创建独立实例，否则复用进程级单例。"""
    global _default_skill_storage, _default_skill_storage_config

    from deerflow.config import get_app_config
    from deerflow.config.skills_config import SkillsConfig

    def _make_storage(skills_config: SkillsConfig, *, host_path: str | None = None, **kwargs) -> SkillStorage:
        """根据技能配置解析后端类并创建存储实例。"""
        from deerflow.reflection import resolve_class

        cls = resolve_class(skills_config.use, SkillStorage)
        return cls(
            host_path=host_path if host_path is not None else str(skills_config.get_skills_path()),
            container_path=skills_config.container_path,
            **kwargs,
        )

    skills_path = kwargs.pop("skills_path", None)
    app_config = kwargs.pop("app_config", None)

    if skills_path is not None:
        if app_config is not None:
            return _make_storage(app_config.skills, host_path=str(skills_path), **kwargs)
        # No app_config: use a default SkillsConfig so we never need to read config.yaml
        # when the caller has already supplied an explicit host path.
        from deerflow.config.skills_config import SkillsConfig

        return _make_storage(SkillsConfig(), host_path=str(skills_path), **kwargs)

    if app_config is not None:
        return _make_storage(app_config.skills, **kwargs)

    # If the singleton was manually injected (e.g. in tests) without a config
    # identity (_default_skill_storage_config is None), skip get_app_config()
    # entirely to avoid requiring a config.yaml on disk.
    if _default_skill_storage is not None and _default_skill_storage_config is None:
        return _default_skill_storage

    app_config_now = get_app_config()

    # Build the singleton under the lock with a double-check so racing cold-start
    # callers construct exactly one instance, and reset_skill_storage() can't null
    # the global out from under a concurrent read. We construct *inside* the lock
    # — mirroring get_memory_storage() rather than sandbox_provider's build-outside-
    # then-discard-the-loser — because SkillStorage has no teardown hook, so an
    # orphaned instance from a losing racer could not be cleaned up.
    with _skill_storage_lock:
        if _default_skill_storage is None or _default_skill_storage_config is not app_config_now:
            _default_skill_storage = _make_storage(app_config_now.skills, **kwargs)
            _default_skill_storage_config = app_config_now
        return _default_skill_storage


def get_or_new_user_skill_storage(user_id: str, **kwargs) -> SkillStorage:
    """按规范化用户 ID 返回隔离存储，并以有容量上限的 LRU 缓存复用实例。"""
    from deerflow.config.paths import make_safe_user_id

    safe_id = make_safe_user_id(user_id)

    # Always acquire lock so move_to_end is safe — makes this a true LRU
    # cache instead of FIFO. The overhead is negligible since dict ops are
    # fast and this function is called once per agent-creation cycle.
    with _user_scoped_storage_lock:
        cached = _user_scoped_storages.get(safe_id)
        if cached is not None:
            _user_scoped_storages.move_to_end(safe_id)
            return cached

        cached = UserScopedSkillStorage(safe_id, **kwargs)
        _user_scoped_storages[safe_id] = cached
        # Evict least-recently-used entry if cache exceeds the ceiling.
        # Since we just moved the current user_id to the end, popitem(last=False)
        # will evict the oldest/least-recently-accessed entry (never the
        # one we just created).
        while len(_user_scoped_storages) > _MAX_USER_SCOPED_STORAGES:
            evicted_key, evicted_val = _user_scoped_storages.popitem(last=False)
            logger.info("Evicted user-scoped skill storage for safe_id=%s (cache ceiling %d)", evicted_key, _MAX_USER_SCOPED_STORAGES)
        return cached


def user_should_see_legacy_skills(user_id: str, **kwargs) -> bool:
    """判断技能发现结果是否包含该用户可见的迁移期旧技能。"""
    if kwargs:
        from deerflow.config.paths import make_safe_user_id

        storage = UserScopedSkillStorage(make_safe_user_id(user_id), **kwargs)
    else:
        storage = get_or_new_user_skill_storage(user_id)
    return any((skill.category.value if hasattr(skill.category, "value") else skill.category) == SkillCategory.LEGACY.value for skill in storage.load_skills(enabled_only=False))


def reset_skill_storage() -> None:
    """清空全局技能存储单例和所有用户级缓存。"""
    global _default_skill_storage, _default_skill_storage_config
    with _skill_storage_lock:
        _default_skill_storage = None
        _default_skill_storage_config = None
    with _user_scoped_storage_lock:
        _user_scoped_storages.clear()


def reset_user_skill_storage(user_id: str | None = None) -> None:
    """清除指定用户的技能存储缓存；未指定用户时清空全部用户缓存。"""
    from deerflow.config.paths import make_safe_user_id

    with _user_scoped_storage_lock:
        if user_id is not None:
            safe_id = make_safe_user_id(user_id)
            _user_scoped_storages.pop(safe_id, None)
        else:
            _user_scoped_storages.clear()


__all__ = [
    "LocalSkillStorage",
    "SkillStorage",
    "UserScopedSkillStorage",
    "get_or_new_skill_storage",
    "get_or_new_user_skill_storage",
    "user_should_see_legacy_skills",
    "reset_skill_storage",
    "reset_user_skill_storage",
]
