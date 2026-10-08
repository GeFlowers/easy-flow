'''定义记忆管理器契约，并提供可插拔后端的单例工厂。

本模块是记忆包中与后端无关的共享核心，定义所有后端实现的 ``MemoryManager``
接口，并由 ``get_memory_manager`` 根据 ``MemoryConfig.manager_class`` 解析活动
后端。新增暴露 ``MANAGER_CLASS`` 的后端子包并配置对应名称即可替换后端。
'''

from __future__ import annotations

import importlib
import logging
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from types import ModuleType
from typing import Any

from deerflow.config.memory_config import get_memory_config

logger = logging.getLogger(__name__)

_BACKENDS_DIR = Path(__file__).parent / "backends"
_MANAGER_CLASS_ATTR = "MANAGER_CLASS"

_memory_manager: MemoryManager | None = None
_backends_cache: dict[str, type[MemoryManager]] | None = None
_manager_lock = threading.Lock()


class MemoryManager(ABC):
    '''定义与后端无关的九项记忆管理器契约。

    记忆按 ``(agent_name, user_id)`` 分桶，``thread_id`` 与会话线程对齐。
    ``get_context`` 返回可直接注入的文本，格式由后端决定；写入方法接收原始
    消息，筛选与纠错、强化识别由后端负责，且后端不必以事实模型存储数据。
    当前尚无调用方的占位方法仍属于契约，可由后续后端实现。
    '''

    def __init__(self, backend_config: dict[str, Any] | None = None) -> None:
        '''接收工厂传入的后端私有配置。

        默认实现原样保存字典；需要解析配置的后端可覆写此方法，不使用私有配置
        的后端可直接继承。
        '''
        self._backend_config = backend_config

    @abstractmethod
    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        '''将会话加入异步、防抖的记忆更新队列。

        ``thread_id`` 标识会话线程，``messages`` 为原始消息；实现方自行筛选消息。
        ``agent_name`` 和 ``user_id`` 分别确定代理与用户分桶，``trace_id`` 用于
        记忆模型调用追踪。
        '''

    @abstractmethod
    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        '''将会话加入立即执行的记忆更新队列，用于摘要前的紧急刷新。'''

    @abstractmethod
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        '''返回指定分桶可直接注入提示词的记忆文本，格式由后端私有配置决定。'''

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        '''检索匹配 ``query`` 的记忆并按相关度返回至多 ``top_k`` 条。

        ``category`` 会在截取数量前过滤，避免类别限定检索被其他类别挤占。
        '''

    @abstractmethod
    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''返回指定分桶的完整记忆文档。'''

    @abstractmethod
    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        '''删除指定分桶的整份记忆文档；当前阶段为占位契约。'''

    @abstractmethod
    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''清空指定分桶的记忆，并返回清空后的空文档。'''

    @abstractmethod
    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''将记忆文档导入指定分桶，并返回合并结果。'''

    @abstractmethod
    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''导出指定分桶的记忆文档；当前阶段为尚无调用方的占位契约。'''

    @abstractmethod
    def shutdown_flush(self, timeout: float) -> bool:
        '''在优雅停机时尽力于 ``timeout`` 内排空待处理更新。

        该方法在网关关闭时刷新后端防抖缓冲区，避免最后一次定时触发后的内存队列
        因重启或终止而丢失。实现必须遵守硬超时，因排空可能包含不可中断的同步
        模型调用。缓冲区清空且无异常时返回 ``True``，超时或失败返回 ``False``；
        无待处理工作的后端应立即返回 ``True``。
        '''


def _scan_backends() -> dict[str, type[MemoryManager]]:
    '''发现 ``backends/<名称>/`` 下可插拔后端并缓存注册表。

    暴露 ``MANAGER_CLASS`` 且为 ``MemoryManager`` 子类的子包以目录名注册；可选
    后端导入失败时仅记录日志并跳过，不能阻断其他可用后端。
    '''
    global _backends_cache
    if _backends_cache is not None:
        return _backends_cache

    registry: dict[str, type[MemoryManager]] = {}
    if not _BACKENDS_DIR.is_dir():
        _backends_cache = registry
        return registry

    for entry in sorted(_BACKENDS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        if not (entry / "__init__.py").is_file():
            continue
        dotted = f"deerflow.agents.memory.backends.{entry.name}"
        try:
            module: ModuleType = importlib.import_module(dotted)
        except Exception:  # noqa: BLE001 - 后端故障不应使工厂失效
            logger.exception("Failed to import memory backend %r; skipping", entry.name)
            continue
        cls = getattr(module, _MANAGER_CLASS_ATTR, None)
        if cls is None:
            continue
        if not (isinstance(cls, type) and issubclass(cls, MemoryManager)):
            logger.warning(
                "Memory backend %r exposes MANAGER_CLASS=%r which is not a MemoryManager subclass; skipping",
                entry.name,
                cls,
            )
            continue
        registry[entry.name] = cls

    _backends_cache = registry
    return registry


def _resolve_manager_class(manager_class: str) -> type[MemoryManager]:
    '''将 ``manager_class`` 配置解析为具体的记忆管理器类。

    先匹配扫描得到的短名称，再支持 ``包.模块:类`` 或 ``包.模块.类`` 导入路径。
    无法解析时必须报错而不能静默回退，以免持久化写入错误存储。
    '''
    registry = _scan_backends()
    if manager_class in registry:
        return registry[manager_class]

    dotted_error: str | None = None
    if ":" in manager_class:
        module_path, _, attr = manager_class.partition(":")
    else:
        module_path, _, attr = manager_class.rpartition(".")
    if module_path and attr:
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            dotted_error = f"cannot import module {module_path!r}: {e}"
        else:
            cls = getattr(module, attr, None)
            if cls is None:
                dotted_error = f"attribute {attr!r} not found in {module_path!r}"
            elif not (isinstance(cls, type) and issubclass(cls, MemoryManager)):
                dotted_error = f"{manager_class!r} resolved to non-MemoryManager {cls!r}"
            else:
                return cls

    raise ValueError(
        f"memory.manager_class={manager_class!r} is not a registered backend name "
        f"(known: {sorted(registry)}) nor a resolvable 'pkg.mod:Cls' path" + (f": {dotted_error}" if dotted_error else "") + ". Fix memory.manager_class in config; refusing to silently fall back to a "
        "different storage backend (memory is persistent state -- a wrong store is a "
        "silent data-integrity footgun)."
    )


def _host_default_tracing_callback(
    invoke_config: dict[str, Any],
    *,
    thread_id: str | None,
    user_id: str | None,
    trace_id: str | None,
    model_name: str | None,
) -> None:
    '''为默认记忆后端的 ``tracing_callback`` 槽位提供宿主默认实现。

    将追踪元数据合并入 ``invoke_config``；未启用相关提供方时无操作。此处把
    ``trace_id`` 映射到 ``deerflow_trace_id``，在宿主边界消除参数名差异。
    '''
    from deerflow.tracing import inject_langfuse_metadata

    inject_langfuse_metadata(
        invoke_config,
        thread_id=thread_id,
        user_id=user_id,
        assistant_id="memory_agent",
        model_name=model_name,
        environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
        deerflow_trace_id=trace_id,
    )


def _host_default_should_keep_hidden_message(additional_kwargs: Any) -> bool:
    '''为默认记忆后端的隐藏消息保留槽位提供默认判断。

    仅保留携带人类输入澄清响应的 ``hide_from_ui`` 消息，以便将用户澄清写入记忆；
    框架内部提醒和查看图像载荷等其他隐藏消息均丢弃。
    '''
    from deerflow.agents.human_input import read_human_input_response

    return read_human_input_response(additional_kwargs) is not None


def _host_default_llm() -> Any:
    '''为默认记忆后端的 ``host_llm`` 槽位创建零配置的默认聊天模型。

    ``create_chat_model(name=None)`` 选择应用默认模型，保持 ``model_name: null``
    的既有语义；未配置模型时返回 ``None``，使记忆提取明确停用而非启动失败。
    '''
    try:
        from deerflow.models import create_chat_model

        return create_chat_model(name=None)
    except Exception:  # noqa: BLE001 - 未配置默认模型属于配置状态，不应导致崩溃
        logger.warning("Could not build host default model for DeerMem memory extraction; memory extraction will be disabled", exc_info=True)
        return None


def get_memory_manager() -> MemoryManager:
    '''返回当前配置对应的 ``MemoryManager`` 单例。

    读取 ``MemoryConfig.manager_class`` 并解析，结果缓存为单例；测试或运行时
    切换后端时可调用 ``reset_memory_manager`` 强制重新解析。
    '''
    global _memory_manager
    if _memory_manager is not None:
        return _memory_manager

    with _manager_lock:
        if _memory_manager is not None:
            return _memory_manager

        cfg = get_memory_config()
        manager_class = cfg.manager_class
        cls = _resolve_manager_class(manager_class)
        backend_config = dict(cfg.backend_config or {})
        if not backend_config.get("storage_path"):
            from deerflow.config.runtime_paths import runtime_home

            backend_config["storage_path"] = str(runtime_home())
        elif not Path(backend_config.get("storage_path", "")).is_absolute():
            from deerflow.config.runtime_paths import runtime_home

            backend_config["storage_path"] = str((Path(runtime_home()) / backend_config["storage_path"]).resolve())
        _resolved_storage_path = Path(backend_config["storage_path"])
        if _resolved_storage_path.is_file():
            raise ValueError(
                f"memory.backend_config.storage_path={backend_config['storage_path']!r} "
                f"resolves to an existing file {_resolved_storage_path}; DeerMem treats "
                f"storage_path as a root DIRECTORY (per-user memory under "
                f"{{storage_path}}/users/{{uid}}/memory.json). Point it at a directory."
            )
        if "tracing_callback" not in backend_config:
            backend_config["tracing_callback"] = _host_default_tracing_callback
        if "should_keep_hidden_message" not in backend_config:
            backend_config["should_keep_hidden_message"] = _host_default_should_keep_hidden_message
        model_cfg = backend_config.get("model")
        if not (isinstance(model_cfg, dict) and model_cfg.get("model")) and "host_llm" not in backend_config:
            backend_config["host_llm"] = _host_default_llm()
        if "trace_context_manager" not in backend_config:
            from deerflow.trace_context import request_trace_context

            backend_config["trace_context_manager"] = request_trace_context
        _memory_manager = cls(backend_config=backend_config)
        logger.info("Memory manager resolved: %s (manager_class=%r)", cls.__name__, manager_class)
        return _memory_manager


def reset_memory_manager() -> None:
    '''清除缓存的管理器单例及后端注册表，供下次调用重新读取配置和扫描后端。'''
    global _memory_manager, _backends_cache
    with _manager_lock:
        _memory_manager = None
        _backends_cache = None
