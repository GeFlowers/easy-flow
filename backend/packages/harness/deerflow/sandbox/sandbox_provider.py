"""管理沙箱提供者的获取、缓存、重置与关闭生命周期。"""

import asyncio
import threading
from abc import ABC, abstractmethod

from deerflow.config import get_app_config
from deerflow.reflection import resolve_class
from deerflow.sandbox.sandbox import Sandbox


class SandboxProvider(ABC):
    """声明创建、查找和释放沙箱的提供者接口。"""

    uses_thread_data_mounts: bool = False
    needs_upload_permission_adjustment: bool = True

    @abstractmethod
    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """获取与可选线程和用户范围关联的沙箱标识。"""
        pass

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """以异步方式获取沙箱标识，默认在线程中调用同步实现。"""
        return await asyncio.to_thread(self.acquire, thread_id, user_id=user_id)

    @abstractmethod
    def get(self, sandbox_id: str) -> Sandbox | None:
        """按标识返回沙箱；不存在时返回空值。"""
        pass

    @abstractmethod
    def release(self, sandbox_id: str) -> None:
        """释放由标识指定的沙箱资源。"""
        pass

    def reset(self) -> None:
        """重置提供者的可复用状态。"""
        pass


_default_sandbox_provider: SandboxProvider | None = None
#
_provider_lock = threading.Lock()


def get_sandbox_provider(**kwargs) -> SandboxProvider:
    """按配置延迟创建并返回进程内共享的沙箱提供者。"""
    global _default_sandbox_provider
    with _provider_lock:
        if _default_sandbox_provider is not None:
            return _default_sandbox_provider

    config = get_app_config()
    cls = resolve_class(config.sandbox.use, SandboxProvider)
    provider = cls(**kwargs)

    with _provider_lock:
        if _default_sandbox_provider is None:
            _default_sandbox_provider = provider
            return provider
        winner = _default_sandbox_provider

    if hasattr(provider, "shutdown"):
        provider.shutdown()
    return winner


def reset_sandbox_provider() -> None:
    """清除共享提供者，并重置其内部状态以应用后续配置。"""
    global _default_sandbox_provider
    with _provider_lock:
        provider = _default_sandbox_provider
        _default_sandbox_provider = None
    if provider is not None:
        provider.reset()


def shutdown_sandbox_provider() -> None:
    """清除共享提供者，并在支持时关闭其持有的资源。"""
    global _default_sandbox_provider
    with _provider_lock:
        provider = _default_sandbox_provider
        _default_sandbox_provider = None
    if provider is not None and hasattr(provider, "shutdown"):
        provider.shutdown()


def set_sandbox_provider(provider: SandboxProvider) -> None:
    """显式设置进程内共享的沙箱提供者。"""
    global _default_sandbox_provider
    with _provider_lock:
        _default_sandbox_provider = provider
