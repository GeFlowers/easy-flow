'''定义记忆存储接口，并实现带缓存和原子文件写入的本地 JSON 存储。'''

import abc
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import DeerMemConfig
from .paths import memory_file_path

logger = logging.getLogger(__name__)


def utc_now_iso_z() -> str:
    '''生成带 Z 时区标记的当前 UTC 时间字符串。'''
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def create_empty_memory() -> dict[str, Any]:
    '''返回包含用户摘要、历史摘要和事实列表的初始记忆文档。'''
    return {
        "version": "1.0",
        "lastUpdated": utc_now_iso_z(),
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


class MemoryStorage(abc.ABC):
    '''规定记忆后端必须实现的加载、强制重载和保存操作。'''

    @abc.abstractmethod
    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''读取指定用户和代理的记忆文档。'''
        pass

    @abc.abstractmethod
    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''绕过缓存重新读取指定用户和代理的记忆文档。'''
        pass

    @abc.abstractmethod
    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        '''持久化指定用户和代理的记忆文档，并报告保存是否成功。'''
        pass


class FileMemoryStorage(MemoryStorage):
    '''使用 JSON 文件持久化记忆，并按文件修改时间维护线程安全的进程内缓存。'''

    def __init__(self, config: DeerMemConfig):
        '''保存存储配置，并初始化按用户/代理隔离的缓存及其互斥锁。'''
        self._config = config
        self._memory_cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], float | None]] = {}
        self._cache_lock = threading.Lock()

    def _get_memory_file_path(self, agent_name: str | None = None, *, user_id: str | None = None) -> Path:
        '''按 DeerMem 配置解析目标记忆 JSON 文件路径。'''
        return memory_file_path(self._config, agent_name, user_id=user_id)

    def _load_memory_from_file(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''从磁盘读取记忆文档；文件不存在、损坏或不可读时返回空记忆结构。'''
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)

        if not file_path.exists():
            return create_empty_memory()

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load memory file: %s", e)
            return create_empty_memory()

    @staticmethod
    def _cache_key(agent_name: str | None = None, *, user_id: str | None = None) -> tuple[str | None, str | None]:
        '''用用户和代理名称构造缓存键，None 表示对应维度使用全局记忆。'''
        return (user_id, agent_name)

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''文件修改时间未变化时返回缓存；文件变化或缓存失效时重新读取并更新缓存。'''
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            current_mtime = None

        with self._cache_lock:
            cached = self._memory_cache.get(cache_key)
            if cached is not None and cached[1] == current_mtime:
                return cached[0]

        memory_data = self._load_memory_from_file(agent_name, user_id=user_id)

        with self._cache_lock:
            self._memory_cache[cache_key] = (memory_data, current_mtime)

        return memory_data

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        '''强制从磁盘载入最新文档，并同步刷新对应缓存及其文件修改时间。'''
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        memory_data = self._load_memory_from_file(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            mtime = None

        with self._cache_lock:
            self._memory_cache[cache_key] = (memory_data, mtime)
        return memory_data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        '''更新时间戳后先写临时文件再原子替换目标文件；成功后更新缓存。'''
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            memory_data = {**memory_data, "lastUpdated": utc_now_iso_z()}

            temp_path = file_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)

            temp_path.replace(file_path)

            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                mtime = None

            with self._cache_lock:
                self._memory_cache[cache_key] = (memory_data, mtime)
            logger.info("Memory saved to %s", file_path)
            return True
        except OSError as e:
            logger.error("Failed to save memory file: %s", e)
            return False


def create_storage(config: DeerMemConfig) -> MemoryStorage:
    '''默认创建文件存储；配置自定义类路径时动态加载并验证类型，失败则明确报错。'''
    storage_class_path = config.storage_class
    if not storage_class_path:
        return FileMemoryStorage(config)

    try:
        module_path, class_name = storage_class_path.rsplit(".", 1)
        import importlib

        module = importlib.import_module(module_path)
        storage_class = getattr(module, class_name)

        if not isinstance(storage_class, type):
            raise TypeError(f"Configured memory storage '{storage_class_path}' is not a class: {storage_class!r}")
        if not issubclass(storage_class, MemoryStorage):
            raise TypeError(f"Configured memory storage '{storage_class_path}' is not a subclass of MemoryStorage")

        return storage_class(config)
    except Exception as e:
        raise ValueError(
            f"backend_config.storage_class={storage_class_path!r} failed to load: {e}. "
            "Refusing to silently fall back to FileMemoryStorage - memory is persistent "
            "state, so a wrong store is a silent data-integrity footgun (a misspelled "
            "class path would otherwise write every fact to local JSON instead of the "
            "intended backend)."
        ) from e
