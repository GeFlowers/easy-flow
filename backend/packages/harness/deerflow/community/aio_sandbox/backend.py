"""定义沙箱后端接口，并提供同步与异步的服务就绪探测。"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod

import httpx
import requests

from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)


def wait_for_sandbox_ready(sandbox_url: str, timeout: int = 30) -> bool:
    """轮询沙箱健康接口，直到服务返回成功或超过等待时限。

    Args:
        sandbox_url: 沙箱服务的根地址。
        timeout: 最长等待秒数。

    Returns:
        服务在时限内就绪时返回 ``True``，否则返回 ``False``。
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{sandbox_url}/v1/sandbox", timeout=5)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False


async def wait_for_sandbox_ready_async(sandbox_url: str, timeout: int = 30, poll_interval: float = 1.0) -> bool:
    """异步轮询沙箱健康接口，等待期间不阻塞事件循环。

    Args:
        sandbox_url: 沙箱服务的根地址。
        timeout: 最长等待秒数。
        poll_interval: 两次探测之间的间隔。

    Returns:
        服务在时限内就绪时返回 ``True``，否则返回 ``False``。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                response = await client.get(f"{sandbox_url}/v1/sandbox", timeout=min(5.0, remaining))
                if response.status_code == 200:
                    return True
            except httpx.RequestError:
                pass
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining))
    return False


class SandboxBackend(ABC):
    """约束本地容器和远程服务后端必须提供的沙箱生命周期操作。"""

    @abstractmethod
    def create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        user_id: str | None = None,
    ) -> SandboxInfo:
        """创建沙箱实例并返回后端连接信息。

        ``extra_mounts`` 仅对管理本地容器的后端有意义；远程后端可忽略。
        """
        ...

    @abstractmethod
    def destroy(self, info: SandboxInfo) -> None:
        """停止或清理由此后端管理的沙箱，并释放其资源。"""
        ...

    @abstractmethod
    def is_alive(self, info: SandboxInfo) -> bool:
        """轻量检查沙箱资源是否仍存在，不要求执行完整服务健康探测。"""
        ...

    @abstractmethod
    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        """根据稳定沙箱标识查找其他进程已创建的实例；找不到或不可用时返回 ``None``。"""
        ...

    def list_running(self) -> list[SandboxInfo]:
        """列出此后端管理的运行实例；不管理本地容器的后端默认返回空列表。"""
        return []
