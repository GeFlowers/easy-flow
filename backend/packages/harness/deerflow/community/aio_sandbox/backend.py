'定义 backend 模块提供的职责与可复用接口。\n\nAbstract base class for sandbox provisioning backends.'

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
    '执行 wait_for_sandbox_ready 的明确职责，并返回与调用约定一致的结果。\n\nPoll sandbox health endpoint until ready or timeout.\n\n    Args:\n        sandbox_url: URL of the sandbox (e.g. http://k3s:30001).\n        timeout: Maximum time to wait in seconds.\n\n    Returns:\n        True if sandbox is ready, False otherwise.\n    '
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
    '执行 wait_for_sandbox_ready_async 的明确职责，并返回与调用约定一致的结果。\n\nAsync variant of sandbox readiness polling.\n\n    Use this from async runtime paths so sandbox startup waits do not block the\n    event loop. The synchronous ``wait_for_sandbox_ready`` function remains for\n    existing synchronous backend/provider call sites.\n    '
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
    '封装 SandboxBackend 的状态、协作关系与公开操作。\n\nAbstract base for sandbox provisioning backends.\n\n    Two implementations:\n    - LocalContainerBackend: starts Docker/Apple Container locally, manages ports\n    - RemoteSandboxBackend: connects to a pre-existing URL (K8s service, external)\n    '

    @abstractmethod
    def create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        user_id: str | None = None,
    ) -> SandboxInfo:
        "创建并返回，并遵守 create 所表达的接口约束。\n\nCreate/provision a new sandbox.\n\n        Args:\n            thread_id: Thread ID for which the sandbox is being created. Useful for backends that want to organize sandboxes by thread.\n            sandbox_id: Deterministic sandbox identifier.\n            extra_mounts: Additional volume mounts as (host_path, container_path, read_only) tuples.\n                Ignored by backends that don't manage containers (e.g., remote).\n            user_id: User bucket that the sandbox should mount or provision for.\n\n        Returns:\n            SandboxInfo with connection details.\n        "
        ...

    @abstractmethod
    def destroy(self, info: SandboxInfo) -> None:
        '执行 destroy 的明确职责，并返回与调用约定一致的结果。\n\nDestroy/cleanup a sandbox and release its resources.\n\n        Args:\n            info: The sandbox metadata to destroy.\n        '
        ...

    @abstractmethod
    def is_alive(self, info: SandboxInfo) -> bool:
        '判断条件是否成立并返回布尔结果，并遵守 is_alive 所表达的接口约束。\n\nQuick check whether a sandbox is still alive.\n\n        This should be a lightweight check (e.g., container inspect)\n        rather than a full health check.\n\n        Args:\n            info: The sandbox metadata to check.\n\n        Returns:\n            True if the sandbox appears to be alive.\n        '
        ...

    @abstractmethod
    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        '执行 discover 的明确职责，并返回与调用约定一致的结果。\n\nTry to discover an existing sandbox by its deterministic ID.\n\n        Used for cross-process recovery: when another process started a sandbox,\n        this process can discover it by the deterministic container name or URL.\n\n        Args:\n            sandbox_id: The deterministic sandbox ID to look for.\n\n        Returns:\n            SandboxInfo if found and healthy, None otherwise.\n        '
        ...

    def list_running(self) -> list[SandboxInfo]:
        "收集并返回，并遵守 list_running 所表达的接口约束。\n\nEnumerate all running sandboxes managed by this backend.\n\n        Used for startup reconciliation: when the process restarts, it needs\n        to discover containers started by previous processes so they can be\n        adopted into the warm pool or destroyed if idle too long.\n\n        The default implementation returns an empty list, which is correct\n        for backends that don't manage local containers (e.g., RemoteSandboxBackend\n        delegates lifecycle to the provisioner which handles its own cleanup).\n\n        Returns:\n            A list of SandboxInfo for all currently running sandboxes.\n        "
        return []
