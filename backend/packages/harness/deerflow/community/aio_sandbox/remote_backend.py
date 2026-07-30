'定义 remote_backend 模块提供的职责与可复用接口。\n\nRemote sandbox backend — delegates Pod lifecycle to the provisioner service.\n\nThe provisioner dynamically creates per-sandbox-id Pods + NodePort Services\nin k3s.  The backend accesses sandbox pods directly via ``k3s:{NodePort}``.\n\nArchitecture:\n    ┌────────────┐  HTTP   ┌─────────────┐  K8s API  ┌──────────┐\n    │ this file  │ ──────▸ │ provisioner │ ────────▸ │   k3s    │\n    │ (backend)  │         │ :8002       │           │ :6443    │\n    └────────────┘         └─────────────┘           └─────┬────┘\n                                                           │ creates\n                           ┌─────────────┐           ┌─────▼──────┐\n                           │   backend   │ ────────▸ │  sandbox   │\n                           │             │  direct   │  Pod(s)    │\n                           └─────────────┘ k3s:NPort └────────────┘\n'

from __future__ import annotations

import logging

import requests

from deerflow.runtime.user_context import get_effective_user_id
from deerflow.skills.storage import user_should_see_legacy_skills

from .backend import SandboxBackend
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)


class RemoteSandboxBackend(SandboxBackend):
    '封装 RemoteSandboxBackend 的状态、协作关系与公开操作。\n\nBackend that delegates sandbox lifecycle to the provisioner service.\n\n    All Pod creation, destruction, and discovery are handled by the\n    provisioner.  This backend is a thin HTTP client.\n\n    Typical config.yaml::\n\n        sandbox:\n          use: deerflow.community.aio_sandbox:AioSandboxProvider\n          provisioner_url: http://provisioner:8002\n          provisioner_api_key: $PROVISIONER_API_KEY\n    '

    def __init__(self, provisioner_url: str, api_key: str = ""):
        '实现 __init__ 协议方法，保持对象交互语义一致。\n\nInitialize with the provisioner service URL and optional API key.\n\n        Args:\n            provisioner_url: URL of the provisioner service\n                             (e.g., ``http://provisioner:8002``).\n            api_key: Value sent as ``X-API-Key`` header on every request.\n                     Leave empty to send no authentication header.\n        '
        self._provisioner_url = provisioner_url.rstrip("/")
        self._api_key = api_key

    @property
    def provisioner_url(self) -> str:
        '执行 provisioner_url 的明确职责，并返回与调用约定一致的结果'
        return self._provisioner_url

    def _auth_headers(self) -> dict[str, str]:
        '执行 _auth_headers 的明确职责，并返回与调用约定一致的结果'
        return {"X-API-Key": self._api_key} if self._api_key else {}

    # ── SandboxBackend interface ──────────────────────────────────────────

    def create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        user_id: str | None = None,
    ) -> SandboxInfo:
        '创建并返回，并遵守 create 所表达的接口约束。\n\nCreate a sandbox Pod + Service via the provisioner.\n\n        Calls ``POST /api/sandboxes`` which creates a dedicated Pod +\n        NodePort Service in k3s.\n        '
        return self._provisioner_create(thread_id, sandbox_id, extra_mounts, user_id=user_id)

    def destroy(self, info: SandboxInfo) -> None:
        '执行 destroy 的明确职责，并返回与调用约定一致的结果。\n\nDestroy a sandbox Pod + Service via the provisioner.'
        self._provisioner_destroy(info.sandbox_id)

    def is_alive(self, info: SandboxInfo) -> bool:
        '判断条件是否成立并返回布尔结果，并遵守 is_alive 所表达的接口约束。\n\nCheck whether the sandbox Pod is running.'
        return self._provisioner_is_alive(info.sandbox_id)

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        '执行 discover 的明确职责，并返回与调用约定一致的结果。\n\nDiscover an existing sandbox via the provisioner.\n\n        Calls ``GET /api/sandboxes/{sandbox_id}`` and returns info if\n        the Pod exists.\n        '
        return self._provisioner_discover(sandbox_id)

    def list_running(self) -> list[SandboxInfo]:
        '收集并返回，并遵守 list_running 所表达的接口约束。\n\nReturn all sandboxes currently managed by the provisioner.\n\n        Calls ``GET /api/sandboxes`` so that ``AioSandboxProvider._reconcile_orphans()``\n        can adopt pods that were created by a previous process and were never\n        explicitly destroyed.\n        Without this, a process restart silently orphans all existing k8s Pods —\n        they stay running forever because the idle checker only\n        tracks in-process state.\n        '
        return self._provisioner_list()

    # ── Provisioner API calls ─────────────────────────────────────────────

    def _provisioner_list(self) -> list[SandboxInfo]:
        '执行 _provisioner_list 的明确职责，并返回与调用约定一致的结果。\n\nGET /api/sandboxes → list all running sandboxes.'
        try:
            resp = requests.get(f"{self._provisioner_url}/api/sandboxes", headers=self._auth_headers(), timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                logger.warning("Provisioner list_running returned non-dict payload: %r", type(data))
                return []

            sandboxes = data.get("sandboxes", [])
            if not isinstance(sandboxes, list):
                logger.warning("Provisioner list_running returned non-list sandboxes: %r", type(sandboxes))
                return []

            infos: list[SandboxInfo] = []
            for sandbox in sandboxes:
                if not isinstance(sandbox, dict):
                    logger.warning("Provisioner list_running entry is not a dict: %r", type(sandbox))
                    continue

                sandbox_id = sandbox.get("sandbox_id")
                sandbox_url = sandbox.get("sandbox_url")
                if isinstance(sandbox_id, str) and sandbox_id and isinstance(sandbox_url, str) and sandbox_url:
                    infos.append(SandboxInfo(sandbox_id=sandbox_id, sandbox_url=sandbox_url))

            logger.info("Provisioner list_running: %d sandbox(es) found", len(infos))
            return infos
        except requests.RequestException as exc:
            logger.warning("Provisioner list_running failed: %s", exc)
            return []

    def _provisioner_create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        user_id: str | None = None,
    ) -> SandboxInfo:
        '执行 _provisioner_create 的明确职责，并返回与调用约定一致的结果。\n\nPOST /api/sandboxes → create Pod + Service.'
        del extra_mounts
        effective_user_id = user_id or get_effective_user_id()
        include_legacy_skills = user_should_see_legacy_skills(effective_user_id)
        try:
            resp = requests.post(
                f"{self._provisioner_url}/api/sandboxes",
                json={
                    "sandbox_id": sandbox_id,
                    "thread_id": thread_id,
                    "user_id": effective_user_id,
                    "include_legacy_skills": include_legacy_skills,
                },
                headers=self._auth_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Provisioner created sandbox {sandbox_id}: sandbox_url={data['sandbox_url']}")
            return SandboxInfo(
                sandbox_id=sandbox_id,
                sandbox_url=data["sandbox_url"],
            )
        except requests.RequestException as exc:
            logger.error(f"Provisioner create failed for {sandbox_id}: {exc}")
            raise RuntimeError(f"Provisioner create failed: {exc}") from exc

    def _provisioner_destroy(self, sandbox_id: str) -> None:
        '执行 _provisioner_destroy 的明确职责，并返回与调用约定一致的结果。\n\nDELETE /api/sandboxes/{sandbox_id} → destroy Pod + Service.'
        try:
            resp = requests.delete(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
                headers=self._auth_headers(),
                timeout=15,
            )
            if resp.ok:
                logger.info(f"Provisioner destroyed sandbox {sandbox_id}")
            else:
                logger.warning(f"Provisioner destroy returned {resp.status_code}: {resp.text}")
        except requests.RequestException as exc:
            logger.warning(f"Provisioner destroy failed for {sandbox_id}: {exc}")

    def _provisioner_is_alive(self, sandbox_id: str) -> bool:
        '执行 _provisioner_is_alive 的明确职责，并返回与调用约定一致的结果。\n\nGET /api/sandboxes/{sandbox_id} → check Pod phase.'
        try:
            resp = requests.get(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
                headers=self._auth_headers(),
                timeout=10,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Provisioner health check failed for {sandbox_id}: {exc}") from exc

        if resp.status_code == 404:
            return False
        if not resp.ok:
            raise RuntimeError(f"Provisioner health check failed for {sandbox_id}: HTTP {resp.status_code} {resp.text}")

        data = resp.json()
        return data.get("status") == "Running"

    def _provisioner_discover(self, sandbox_id: str) -> SandboxInfo | None:
        '执行 _provisioner_discover 的明确职责，并返回与调用约定一致的结果。\n\nGET /api/sandboxes/{sandbox_id} → discover existing sandbox.'
        try:
            resp = requests.get(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
                headers=self._auth_headers(),
                timeout=10,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return SandboxInfo(
                sandbox_id=sandbox_id,
                sandbox_url=data["sandbox_url"],
            )
        except requests.RequestException as exc:
            logger.debug(f"Provisioner discover failed for {sandbox_id}: {exc}")
            return None
