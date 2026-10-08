'''管理 E2B 远程沙箱的配置、创建、复用、预热、租约回收和文件上传。

``E2BSandboxProvider`` 是面向 E2B 云服务的 DeerFlow :class:`SandboxProvider`。

配置从 :class:`SandboxConfig` 读取。该模型设置了 ``extra="allow"``，因此即使
模型未声明下列字段，也可在 ``config.yaml`` 的 ``sandbox:`` 下配置：

.. code-block:: yaml

    sandbox:
      use: deerflow.community.e2b_sandbox:E2BSandboxProvider
      api_key: $E2B_API_KEY            # 必填，也可通过 E2B_API_KEY 环境变量传入
      template: code-interpreter-v1     # 默认使用 e2b 代码解释器模板
      domain: e2b.dev                  # 可选，用于自托管 e2b
      idle_timeout: 600                # 转发给 ``set_timeout``
      replicas: 3                      # 并发沙箱数量上限
      mounts:                          # 沙箱启动时一次性上传文件
        - host_path: /data/skills
          container_path: /home/user/skills
          read_only: true
      environment:                     # 创建时作为 e2b 的 ``envs`` 传入
        OPENAI_API_KEY: $OPENAI_API_KEY
'''

from __future__ import annotations

import asyncio
import atexit
import hashlib
import logging
import os
import shlex
import signal
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from e2b_code_interpreter import Sandbox as E2BClientSandbox

from deerflow.config import get_app_config
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

from .e2b_sandbox import DEFAULT_E2B_HOME_DIR, E2BSandbox, _is_sandbox_gone_error

logger = logging.getLogger(__name__)


DEFAULT_TEMPLATE = "code-interpreter-v1"
DEFAULT_IDLE_TIMEOUT = 1800
DEFAULT_REPLICAS = 3
MAX_E2B_TIMEOUT = 24 * 60 * 60

META_KEY_USER = "deer_flow_user"
META_KEY_THREAD = "deer_flow_thread"
META_KEY_PROVIDER = "deer_flow_provider"
META_VAL_PROVIDER = "e2b_sandbox_provider"


class E2BSandboxProvider(SandboxProvider):
    '''管理远程沙箱生命周期，并按用户与线程复用运行中或预热的实例。'''

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True


    def __init__(self) -> None:
        '''初始化实例索引、线程锁和预热池，读取配置并注册进程退出清理。'''
        self._lock = threading.Lock()
        self._sandboxes: dict[str, E2BSandbox] = {}
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        self._thread_locks: dict[tuple[str, str], threading.Lock] = {}
        self._warm_pool: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._shutdown_called = False

        self._config = self._load_config()

        atexit.register(self.shutdown)
        self._register_signal_handlers()

    def _load_config(self) -> dict[str, Any]:
        '''从沙箱应用配置和环境变量解析密钥、镜像、超时、副本数、挂载及环境变量。'''
        sandbox_config = get_app_config().sandbox

        def _opt(name: str, default: Any = None) -> Any:
            '''读取沙箱配置中的可选扩展字段，并在未设置时返回默认值。'''
            return getattr(sandbox_config, name, default)

        api_key = _opt("api_key") or os.environ.get("E2B_API_KEY")
        if not api_key:
            logger.warning("E2BSandboxProvider: no api_key configured (set sandbox.api_key in config.yaml or the E2B_API_KEY environment variable). The SDK will fail on the first acquire() until this is provided.")

        idle_timeout = _opt("idle_timeout")
        if idle_timeout is None:
            idle_timeout = DEFAULT_IDLE_TIMEOUT
        idle_timeout = max(0, min(int(idle_timeout), MAX_E2B_TIMEOUT))

        replicas = _opt("replicas")
        replicas = DEFAULT_REPLICAS if replicas is None else max(1, int(replicas))

        return {
            "api_key": api_key,
            "template": _opt("template") or _opt("image") or DEFAULT_TEMPLATE,
            "domain": _opt("domain"),
            "home_dir": _opt("home_dir") or DEFAULT_E2B_HOME_DIR,
            "idle_timeout": idle_timeout,
            "replicas": replicas,
            "mounts": _opt("mounts") or [],
            "environment": self._resolve_env_vars(_opt("environment") or {}),
        }

    @staticmethod
    def _resolve_env_vars(env_config: dict[str, str]) -> dict[str, str]:
        '''解析环境变量配置中的 $NAME 引用，其余值统一转换为字符串。'''
        resolved: dict[str, str] = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                resolved[key] = os.environ.get(value[1:], "")
            else:
                resolved[key] = "" if value is None else str(value)
        return resolved

    def _get_sandbox_cls(self) -> type[E2BClientSandbox]:
        '''返回 E2B 客户端沙箱类，便于测试替换和统一创建调用。'''
        return E2BClientSandbox


    @staticmethod
    def _effective_acquire_user_id(user_id: str | None) -> str:
        '''优先采用调用方提供的用户标识，否则从当前请求上下文解析用户。'''
        return user_id or get_effective_user_id()

    @staticmethod
    def _thread_key(thread_id: str, user_id: str) -> tuple[str, str]:
        '''生成用于隔离不同用户线程沙箱的复合索引键。'''
        return (user_id, thread_id)

    @staticmethod
    def _stable_seed(thread_id: str, user_id: str) -> str:
        '''根据用户和线程标识生成稳定摘要，用于匹配预热沙箱。'''
        return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:16]


    def _register_signal_handlers(self) -> None:
        '''注册进程终止信号处理器，在退出前关闭当前提供方管理的沙箱。'''
        try:
            self._original_sigterm = signal.getsignal(signal.SIGTERM)
            self._original_sigint = signal.getsignal(signal.SIGINT)
            self._original_sighup = signal.getsignal(signal.SIGHUP) if hasattr(signal, "SIGHUP") else None
        except (ValueError, OSError):
            return

        def _handler(signum, frame):
            '''先关闭沙箱，再按原信号处理方式继续执行默认或已有处理器。'''
            self.shutdown()
            if signum == signal.SIGTERM:
                original = self._original_sigterm
            elif hasattr(signal, "SIGHUP") and signum == signal.SIGHUP:
                original = self._original_sighup
            else:
                original = self._original_sigint
            if callable(original):
                original(signum, frame)
            elif original == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        for sig_name in ("SIGTERM", "SIGINT", "SIGHUP"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                logger.debug(
                    "Could not register %s handler (likely not running on main thread)",
                    sig_name,
                )

    def _get_thread_lock(self, thread_id: str, user_id: str) -> threading.Lock:
        '''取得用户与线程专属锁，避免同一会话并发申请多个沙箱。'''
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            lock = self._thread_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._thread_locks[key] = lock
            return lock

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        '''同步申请沙箱，按当前线程依次尝试复用、回收、远程发现和新建。'''
        effective_user_id = self._effective_acquire_user_id(user_id)
        if thread_id:
            with self._get_thread_lock(thread_id, effective_user_id):
                return self._acquire_internal(thread_id, user_id=effective_user_id)
        return self._acquire_internal(thread_id, user_id=effective_user_id)

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        '''在线程池中运行同步申请流程，避免阻塞异步调用方。'''
        effective_user_id = self._effective_acquire_user_id(user_id)
        return await asyncio.to_thread(self.acquire, thread_id, user_id=effective_user_id)

    def _acquire_internal(self, thread_id: str | None, *, user_id: str) -> str:
        '''按优先级尝试复用进程内实例、回收预热实例、发现远程实例，最后才创建。'''
        if thread_id:
            cached = self._reuse_in_process_sandbox(thread_id, user_id=user_id)
            if cached is not None:
                return cached

        if thread_id:
            reclaimed = self._reclaim_warm_pool_sandbox(thread_id, user_id=user_id)
            if reclaimed is not None:
                return reclaimed

        if thread_id:
            discovered = self._discover_remote_sandbox(thread_id, user_id=user_id)
            if discovered is not None:
                return discovered
        return self._create_sandbox(thread_id, user_id=user_id)

    def _reuse_in_process_sandbox(self, thread_id: str, *, user_id: str) -> str | None:
        '''校验线程映射的进程内实例仍可响应，失效时清除缓存并允许重新创建。'''
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            sid = self._thread_sandboxes.get(key)
            if sid is None:
                return None
            sandbox = self._sandboxes.get(sid)
            if sandbox is None:
                self._thread_sandboxes.pop(key, None)
                return None

        if sandbox.is_dead or not sandbox.ping():
            logger.warning(
                "In-process e2b sandbox %s is dead (reaped by e2b control plane); evicting cache so acquire() can rebuild a fresh sandbox",
                sid,
            )
            with self._lock:
                self._sandboxes.pop(sid, None)
                self._thread_sandboxes.pop(key, None)
            try:
                sandbox.close()
            except Exception:
                pass
            return None

        try:
            self._refresh_remote_timeout(sandbox.client)
        except Exception as e:  # pragma: no cover - 防御性处理
            logger.debug("Failed to refresh timeout on reuse: %s", e)

        logger.info(
            "Reusing in-process e2b sandbox %s for user/thread %s/%s",
            sid,
            user_id,
            thread_id,
        )
        return sid

    def _reclaim_warm_pool_sandbox(self, thread_id: str, *, user_id: str) -> str | None:
        '''按用户线程摘要从预热池取回实例，重新连接、探活并恢复路径配置。'''
        key = self._thread_key(thread_id, user_id)
        seed = self._stable_seed(thread_id, user_id)
        with self._lock:
            target_id = next(
                (sid for sid, (s, _) in self._warm_pool.items() if s == seed),
                None,
            )
            if target_id is None:
                return None
            self._warm_pool.pop(target_id)

        sandbox_cls = self._get_sandbox_cls()
        try:
            client = self._reconnect_client(sandbox_cls, target_id)
        except Exception as e:
            logger.warning(
                "Warm-pool e2b sandbox %s failed to reconnect, dropping: %s",
                target_id,
                e,
            )
            return None

        if not self._client_alive(client):
            logger.warning(
                "Warm-pool e2b sandbox %s is no longer alive (reaped by control plane); dropping and falling back to create",
                target_id,
            )
            self._safe_close_client(client)
            return None

        self._refresh_remote_timeout(client)
        try:
            self._bootstrap_sandbox_paths(client)
        except Exception as e:
            logger.debug("bootstrap on warm-pool reclaim failed: %s", e)
        sandbox = E2BSandbox(id=target_id, client=client, home_dir=self._config["home_dir"])
        with self._lock:
            self._sandboxes[target_id] = sandbox
            self._thread_sandboxes[key] = target_id
        logger.info(
            "Reclaimed warm-pool e2b sandbox %s for user/thread %s/%s",
            target_id,
            user_id,
            thread_id,
        )
        return target_id

    def _discover_remote_sandbox(self, thread_id: str, *, user_id: str) -> str | None:
        '''按用户和线程元数据分页查找远程实例，连接并验证后登记到本进程缓存。'''
        sandbox_cls = self._get_sandbox_cls()
        seed = self._stable_seed(thread_id, user_id)
        list_kwargs = self._common_kwargs()
        try:
            running = sandbox_cls.list(  # type: ignore[attr-defined]
                query={
                    "metadata": {
                        META_KEY_PROVIDER: META_VAL_PROVIDER,
                        META_KEY_USER: user_id,
                        META_KEY_THREAD: thread_id,
                    }
                },
                **list_kwargs,
            )
        except TypeError:
            try:
                running = sandbox_cls.list(
                    metadata={
                        META_KEY_PROVIDER: META_VAL_PROVIDER,
                        META_KEY_USER: user_id,
                        META_KEY_THREAD: thread_id,
                    },
                    **list_kwargs,
                )
            except Exception as e:
                logger.debug("e2b Sandbox.list() unavailable, skipping discovery: %s", e)
                return None
        except Exception as e:
            logger.debug(
                "e2b Sandbox.list() raised while discovering thread %s: %s",
                thread_id,
                e,
            )
            return None

        def _iter_running(obj):
            '''兼容直接返回的列表和分页器，逐页遍历可用的运行中实例。'''
            if obj is None:
                return
            if hasattr(obj, "next_items") and hasattr(obj, "has_next"):
                for _ in range(50):
                    try:
                        page = obj.next_items()
                    except Exception as exc:
                        logger.debug("SandboxPaginator.next_items() failed: %s", exc)
                        return
                    if not page:
                        return
                    yield from page
                    if not getattr(obj, "has_next", False):
                        return
                return
            try:
                yield from obj
            except TypeError:
                logger.debug("Sandbox.list() returned non-iterable %s; ignoring", type(obj).__name__)

        target_id: str | None = None
        for entry in _iter_running(running):
            sid = getattr(entry, "sandbox_id", None) or (entry.get("sandbox_id") if isinstance(entry, dict) else None)
            metadata = getattr(entry, "metadata", None) or (entry.get("metadata") if isinstance(entry, dict) else {}) or {}
            if metadata.get(META_KEY_USER) != user_id:
                continue
            if metadata.get(META_KEY_THREAD) != thread_id:
                continue
            target_id = sid
            break

        if not target_id:
            return None

        try:
            client = self._reconnect_client(sandbox_cls, target_id)
        except Exception as e:
            logger.warning(
                "Discovered e2b sandbox %s could not be reconnected: %s",
                target_id,
                e,
            )
            return None

        if not self._client_alive(client):
            logger.warning(
                "Discovered e2b sandbox %s is no longer alive; falling back to create",
                target_id,
            )
            self._safe_close_client(client)
            return None

        self._refresh_remote_timeout(client)
        try:
            self._bootstrap_sandbox_paths(client)
        except Exception as e:
            logger.debug("bootstrap on remote discovery failed: %s", e)
        sandbox = E2BSandbox(id=target_id, client=client, home_dir=self._config["home_dir"])
        with self._lock:
            self._sandboxes[target_id] = sandbox
            self._thread_sandboxes[self._thread_key(thread_id, user_id)] = target_id
        logger.info(
            "Discovered remote e2b sandbox %s for user/thread %s/%s (seed=%s)",
            target_id,
            user_id,
            thread_id,
            seed,
        )
        return target_id

    def _create_sandbox(self, thread_id: str | None, *, user_id: str) -> str:
        '''按配置创建远程实例，初始化虚拟目录、上传挂载文件并登记用户线程映射。'''
        replicas = int(self._config["replicas"])
        with self._lock:
            in_use = len(self._sandboxes) + len(self._warm_pool)
        if in_use >= replicas:
            evicted = self._evict_oldest_warm()
            if evicted is None:
                logger.warning(
                    "All %d e2b replica slots are in active use; creating a new sandbox beyond the soft limit (active=%d, warm=%d)",
                    replicas,
                    len(self._sandboxes),
                    len(self._warm_pool),
                )

        sandbox_cls = self._get_sandbox_cls()
        metadata: dict[str, str] = {
            META_KEY_PROVIDER: META_VAL_PROVIDER,
        }
        if thread_id:
            metadata[META_KEY_USER] = user_id
            metadata[META_KEY_THREAD] = thread_id

        create_kwargs: dict[str, Any] = {
            "template": self._config["template"],
            "metadata": metadata,
            **self._common_kwargs(),
        }
        if self._config["idle_timeout"] > 0:
            create_kwargs["timeout"] = self._config["idle_timeout"]
        if self._config["environment"]:
            create_kwargs["envs"] = self._config["environment"]

        try:
            client = sandbox_cls.create(**create_kwargs)  # type: ignore[attr-defined]
        except Exception as e:
            logger.error("Failed to create e2b sandbox: %s", e)
            raise

        sandbox_id: str = getattr(client, "sandbox_id", None) or str(uuid.uuid4())[:8]

        try:
            self._bootstrap_sandbox_paths(client)
        except Exception as e:
            logger.warning(
                "Failed to bootstrap virtual paths in e2b sandbox %s: %s",
                sandbox_id,
                e,
            )

        try:
            self._apply_mounts(client)
        except Exception as e:
            logger.warning("Failed to apply some mounts to e2b sandbox %s: %s", sandbox_id, e)

        sandbox = E2BSandbox(id=sandbox_id, client=client, home_dir=self._config["home_dir"])
        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            if thread_id:
                self._thread_sandboxes[self._thread_key(thread_id, user_id)] = sandbox_id

        logger.info(
            "Created e2b sandbox %s for user/thread %s/%s (template=%s, replicas=%d)",
            sandbox_id,
            user_id,
            thread_id,
            self._config["template"],
            replicas,
        )
        return sandbox_id

    def _common_kwargs(self) -> dict[str, Any]:
        '''构造创建、连接和列举远程实例时共用的鉴权及服务域参数。'''
        kwargs: dict[str, Any] = {}
        if self._config["api_key"]:
            kwargs["api_key"] = self._config["api_key"]
        if self._config["domain"]:
            kwargs["domain"] = self._config["domain"]
        return kwargs

    def _reconnect_client(self, sandbox_cls: type[E2BClientSandbox], sandbox_id: str) -> E2BClientSandbox:
        '''使用指定客户端类和共用连接参数，按标识连接已有 E2B 沙箱。'''
        return sandbox_cls.connect(sandbox_id, **self._common_kwargs())  # type: ignore[attr-defined]

    def _refresh_remote_timeout(self, client: E2BClientSandbox) -> None:
        '''将配置的空闲超时传给 E2B 控制平面，为远程实例续期。'''
        idle_timeout = int(self._config["idle_timeout"])
        if idle_timeout <= 0:
            return
        set_timeout = getattr(client, "set_timeout", None)
        if not callable(set_timeout):
            return
        try:
            set_timeout(idle_timeout)
        except Exception as e:  # pragma: no cover - 防御性处理
            logger.debug("Failed to set timeout on e2b sandbox: %s", e)

    @staticmethod
    def _client_alive(client: E2BClientSandbox) -> bool:
        '''尽力检查刚重新连接的 E2B 客户端是否仍可执行命令。

        某些客户端版本的 ``Sandbox.connect`` 可能成功连接已暂停或过期的沙箱，
        直到首次执行命令才报错。此处执行简单的 ``true`` 命令，在获取实例时
        发现失效情况并转而创建新沙箱，避免工具调用中途出现 "sandbox not found"。

        命令成功时返回 ``True``；遇到沙箱不存在或暂停的错误时返回 ``False``。
        其他临时错误按仍然可用处理，避免偶发网络问题导致清空缓存。
        '''
        try:
            client.commands.run("true")
            return True
        except Exception as e:
            if _is_sandbox_gone_error(e):
                return False
            logger.debug("e2b client liveness probe non-fatal error: %s", e)
            return True

    @staticmethod
    def _safe_close_client(client: E2BClientSandbox | None) -> None:
        '''关闭 *client* 的宿主机侧网络连接，不向外抛出异常。

        用于已知 E2B 虚拟机因暂停或过期而不可达的清理流程，仅释放网关进程中的
        套接字。所有异常均记录为调试日志并忽略。
        '''
        if client is None:
            return
        for attr in ("close", "_transport"):
            target = getattr(client, attr, None)
            if target is None:
                continue
            close = target if callable(target) else getattr(target, "close", None)
            if not callable(close):
                continue
            try:
                close()
                return
            except Exception as e:  # pragma: no cover - 防御性处理
                logger.debug("e2b client close raised: %s", e)
                return

    def _bootstrap_sandbox_paths(self, client: E2BClientSandbox) -> None:
        '''在 E2B 虚拟机内建立 DeerFlow 所需的虚拟目录布局。

        本地沙箱提供可写的 ``/mnt/user-data/{workspace,uploads,outputs}`` 和
        ``/mnt/acp-workspace``，代理提示词也要求将产物写入这些位置。
        默认 ``code-interpreter`` 模板使用普通账户 ``user``（用户编号 1000），
        而 ``/mnt`` 属于 ``root``，直接创建其下的目录会出现 ``Permission denied``。

        沙箱启动时先在配置的主目录（默认为 ``/home/user``）中创建可写的
        workspace、uploads、outputs 和 acp-workspace 目录，再通过 ``sudo``
        将虚拟路径链接到实际目录，必要时赋予 ``/mnt`` 读取和进入权限。
        命令与 :class:`E2BSandbox._resolve_path` 因而访问相同位置。

        默认模板允许 ``user`` 免密执行 ``sudo``。自定义模板移除此权限时，
        初始化失败会记录警告；``E2BSandbox`` 的路径映射仍可支持读写和目录
        列举接口，但代理直接执行使用虚拟路径的命令仍可能失败。
        '''
        home_dir = self._config["home_dir"].rstrip("/") or "/home/user"
        bootstrap_script = (
            f"set -e; "
            f"mkdir -p {shlex.quote(home_dir)}/workspace "
            f"{shlex.quote(home_dir)}/uploads "
            f"{shlex.quote(home_dir)}/outputs "
            f"{shlex.quote(home_dir)}/acp-workspace; "
            f"if [ ! -e /mnt/user-data ] || [ -L /mnt/user-data ]; then "
            f"  sudo ln -sfn {shlex.quote(home_dir)} /mnt/user-data; "
            f"fi; "
            f"if [ ! -e /mnt/acp-workspace ] || [ -L /mnt/acp-workspace ]; then "
            f"  sudo ln -sfn {shlex.quote(home_dir)}/acp-workspace /mnt/acp-workspace; "
            f"fi; "
            f"sudo chmod a+rx /mnt 2>/dev/null || true; "
            f"echo BOOTSTRAP_OK"
        )

        try:
            result = client.commands.run(bootstrap_script)
        except Exception as e:
            logger.warning(
                "e2b bootstrap script raised: %s (agent shell commands using /mnt/user-data may fail until the VM is recycled)",
                e,
            )
            return

        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        exit_code = getattr(result, "exit_code", 0)
        if exit_code not in (0, None) or "BOOTSTRAP_OK" not in stdout:
            logger.warning(
                "e2b bootstrap script exited with code=%s; stderr=%s",
                exit_code,
                stderr.strip(),
            )

    def _apply_mounts(self, client: E2BClientSandbox) -> None:
        '''把配置的宿主机目录内容复制到远程实例目标路径，而非建立共享挂载。'''
        mounts = self._config.get("mounts") or []
        if not mounts:
            return
        for mount in mounts:
            try:
                host_path = Path(getattr(mount, "host_path", "") or "")
                container_path = (getattr(mount, "container_path", "") or "").rstrip("/")
                read_only = bool(getattr(mount, "read_only", False))
            except AttributeError:
                host_path = Path(mount.get("host_path", ""))
                container_path = (mount.get("container_path", "") or "").rstrip("/")
                read_only = bool(mount.get("read_only", False))

            if not host_path.exists():
                logger.warning("Skipping e2b mount: host_path %s does not exist", host_path)
                continue
            if not container_path.startswith("/"):
                logger.warning(
                    "Skipping e2b mount: container_path %s must be absolute",
                    container_path,
                )
                continue

            try:
                make_dir = getattr(client.files, "make_dir", None)
                if callable(make_dir):
                    make_dir(container_path)
            except Exception as e:
                logger.debug("make_dir(%s) failed (continuing): %s", container_path, e)

            try:
                self._upload_tree(client, host_path, container_path, read_only)
            except Exception as e:
                logger.warning("Failed to upload mount %s -> %s: %s", host_path, container_path, e)

    _SYNC_BACK_SUBDIRS = ("outputs", "workspace")

    def _sync_outputs_to_host(
        self,
        sandbox: E2BSandbox,
        *,
        thread_id: str,
        user_id: str,
    ) -> None:
        '''将 E2B 虚拟机中的代理产物同步回宿主机线程目录。

        DeerFlow 的 ``/api/threads/{tid}/artifacts/...`` 端点从宿主机对应线程的
        ``user-data/`` 目录读取文件，参见 :meth:`Paths.sandbox_outputs_dir`。
        本地沙箱通过路径映射直接写入该目录，而 E2B 虚拟机没有共享宿主文件系统，
        因此需要在释放沙箱时显式下载产物。

        仅下载宿主机侧不存在或大小不同的文件。目录内容未变化时，释放过程仅需
        一次远程目录查询，避免每轮工具调用都重复下载大型文档或数据集。

        同步失败仅记录警告，不向外抛出异常，以免影响沙箱生命周期；底层客户端
        错误已在其他位置记录。
        '''
        from deerflow.config.paths import get_paths

        client = sandbox.client
        if client is None:
            logger.debug("Skip output sync: e2b client already closed for sandbox %s", sandbox.id)
            return

        home_dir = sandbox.home_dir.rstrip("/") or "/home/user"
        paths = get_paths()

        thread_root = paths.thread_dir(thread_id, user_id=user_id) / "user-data"
        host_targets: dict[str, Path] = {sub: thread_root / sub for sub in self._SYNC_BACK_SUBDIRS}

        find_targets = " ".join(shlex.quote(f"{home_dir}/{sub}") for sub in self._SYNC_BACK_SUBDIRS)
        list_cmd = f'for d in {find_targets}; do   [ -d "$d" ] && find "$d" -type f -printf \'%s\\t%p\\0\' 2>/dev/null; done'

        try:
            result = client.commands.run(list_cmd)
        except Exception as e:
            logger.warning("e2b sync: list command failed: %s", e)
            if _is_sandbox_gone_error(e):
                with sandbox._lock:
                    sandbox._dead = True
            return

        stdout = getattr(result, "stdout", "") or ""
        if not stdout:
            return

        synced = 0
        skipped = 0
        from .e2b_sandbox import _MAX_DOWNLOAD_SIZE

        for entry in stdout.split("\0"):
            entry = entry.strip()
            if not entry:
                continue
            try:
                size_str, remote_path = entry.split("\t", 1)
                remote_size = int(size_str)
            except ValueError:
                logger.debug("e2b sync: unparseable entry %r", entry)
                continue

            if remote_size > _MAX_DOWNLOAD_SIZE:
                logger.warning(
                    "e2b sync: skipping oversize artefact %s (%d bytes > %d cap)",
                    remote_path,
                    remote_size,
                    _MAX_DOWNLOAD_SIZE,
                )
                skipped += 1
                continue

            sub_match: tuple[str, Path, str] | None = None
            for sub, host_root in host_targets.items():
                prefix = f"{home_dir}/{sub}/"
                if remote_path == f"{home_dir}/{sub}":
                    continue
                if remote_path.startswith(prefix):
                    rel = remote_path[len(prefix) :]
                    virtual_path = f"/mnt/user-data/{sub}/{rel}"
                    sub_match = (sub, host_root / rel, virtual_path)
                    break
            if sub_match is None:
                continue
            _sub, host_path, virtual_path = sub_match

            try:
                if host_path.exists() and host_path.stat().st_size == remote_size:
                    skipped += 1
                    continue
            except OSError:
                pass

            try:
                data = sandbox.download_file(virtual_path)
            except Exception as e:
                logger.warning(
                    "e2b sync: failed to download %s from sandbox %s: %s",
                    virtual_path,
                    sandbox.id,
                    e,
                )
                continue

            try:
                host_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = host_path.with_name(host_path.name + ".e2bsync.tmp")
                tmp_path.write_bytes(data)
                tmp_path.replace(host_path)
                synced += 1
            except OSError as e:
                logger.warning("e2b sync: failed to write %s on host: %s", host_path, e)

        if synced or skipped:
            logger.info(
                "e2b sync: sandbox=%s thread=%s synced=%d skipped=%d",
                sandbox.id,
                thread_id,
                synced,
                skipped,
            )

    @staticmethod
    def _upload_tree(
        client: E2BClientSandbox,
        src: Path,
        dest_dir: str,
        read_only: bool,
    ) -> None:
        '''将宿主机 ``src`` 的文件递归上传到沙箱内的 ``dest_dir``，可选设为只读。'''
        if src.is_file():
            target = f"{dest_dir}/{src.name}"
            with src.open("rb") as fh:
                client.files.write(target, fh.read())
            if read_only:
                try:
                    client.commands.run(f"chmod a-w {shlex.quote(target)}")
                except Exception:
                    pass
            return

        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src).as_posix()
            target = f"{dest_dir}/{rel}"
            try:
                make_dir = getattr(client.files, "make_dir", None)
                if callable(make_dir):
                    parent = target.rsplit("/", 1)[0]
                    if parent and parent != dest_dir:
                        make_dir(parent)
            except Exception:
                pass
            with path.open("rb") as fh:
                client.files.write(target, fh.read())
        if read_only:
            try:
                client.commands.run(f"chmod -R a-w {shlex.quote(dest_dir)}")
            except Exception:
                pass

    def _evict_oldest_warm(self) -> str | None:
        '''从预热池中移除最久未使用实例，以释放配置的副本容量。'''
        with self._lock:
            if not self._warm_pool:
                return None
            evict_id, (_, _) = self._warm_pool.popitem(last=False)

        try:
            client = self._reconnect_client(self._get_sandbox_cls(), evict_id)
        except Exception as e:
            logger.warning(
                "Evicted warm-pool e2b sandbox %s could not be reconnected for kill: %s",
                evict_id,
                e,
            )
            return evict_id

        try:
            kill = getattr(client, "kill", None)
            if callable(kill):
                kill()
        except Exception as e:
            logger.warning("Failed to kill evicted e2b sandbox %s: %s", evict_id, e)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        logger.info("Evicted warm-pool e2b sandbox %s", evict_id)
        return evict_id

    def get(self, sandbox_id: str) -> Sandbox | None:
        '''按沙箱标识读取当前进程登记的活动沙箱，不存在时返回 None。'''
        with self._lock:
            return self._sandboxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        '''解除沙箱与线程的活动映射，并在容量允许时放入预热池，保留云虚拟机。

        E2B 沙箱具有服务端强制超时，此处刷新超时，使预热条目在释放后至少保持
        一个 ``idle_timeout`` 窗口的有效期。已失效的实例直接销毁，不进入预热池。
        '''
        sandbox: E2BSandbox | None = None
        seed: str | None = None

        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            removed_keys = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in removed_keys:
                self._thread_sandboxes.pop(key, None)
            if removed_keys:
                user_id, thread_id = removed_keys[0]
                seed = self._stable_seed(thread_id, user_id)

        if sandbox is None:
            return

        if sandbox.is_dead:
            logger.info(
                "Releasing dead e2b sandbox %s; skipping output sync and warm pool, killing remote VM",
                sandbox_id,
            )
            self._kill_and_close(sandbox)
            return

        sync_failed_due_to_dead_vm = False
        if seed is not None and removed_keys:
            user_id_sync, thread_id_sync = removed_keys[0]
            try:
                self._sync_outputs_to_host(sandbox, thread_id=thread_id_sync, user_id=user_id_sync)
            except Exception as e:  # pragma: no cover - 防御性处理
                logger.warning(
                    "Failed to mirror e2b sandbox %s outputs to host: %s",
                    sandbox_id,
                    e,
                )
            if sandbox.is_dead:
                sync_failed_due_to_dead_vm = True

        if sync_failed_due_to_dead_vm:
            logger.info(
                "Sandbox %s was reaped during release; not parking in warm pool",
                sandbox_id,
            )
            self._kill_and_close(sandbox)
            return

        try:
            self._refresh_remote_timeout(sandbox.client)
        except Exception as e:
            logger.debug("Failed to refresh timeout during release: %s", e)

        try:
            sandbox.close()
        except Exception as e:
            logger.warning("Error closing e2b sandbox %s during release: %s", sandbox_id, e)

        with self._lock:
            self._warm_pool[sandbox_id] = (seed or "", time.time())
            self._warm_pool.move_to_end(sandbox_id)
        logger.info("Released e2b sandbox %s to warm pool", sandbox_id)

    def _kill_and_close(self, sandbox: E2BSandbox) -> None:
        '''从缓存和预热池移除实例，随后尽力关闭远程连接和沙箱。'''
        client = getattr(sandbox, "_client", None)
        if client is not None:
            kill = getattr(client, "kill", None)
            if callable(kill):
                try:
                    kill()
                except Exception as e:
                    logger.debug(
                        "kill() on e2b sandbox %s raised (probably already gone): %s",
                        sandbox.id,
                        e,
                    )
        try:
            sandbox.close()
        except Exception:
            pass

    def reset(self) -> None:
        '''关闭全部活动及预热沙箱，并清空实例、线程和锁索引。'''
        with self._lock:
            self._sandboxes.clear()
            self._thread_sandboxes.clear()
            self._thread_locks.clear()
            self._warm_pool.clear()

    def shutdown(self) -> None:
        '''幂等停止提供方，关闭所有实例并恢复此前注册的进程信号处理器。'''
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            active = list(self._sandboxes.items())
            warm_ids = list(self._warm_pool.keys())
            self._sandboxes.clear()
            self._warm_pool.clear()
            self._thread_sandboxes.clear()

        logger.info(
            "Shutting down E2BSandboxProvider: %d active + %d warm sandboxes",
            len(active),
            len(warm_ids),
        )

        for sandbox_id, sandbox in active:
            try:
                kill = getattr(sandbox.client, "kill", None)
                if callable(kill):
                    kill()
            except Exception as e:
                logger.warning(
                    "Failed to kill active e2b sandbox %s during shutdown: %s",
                    sandbox_id,
                    e,
                )
            try:
                sandbox.close()
            except Exception:
                pass

        sandbox_cls = self._get_sandbox_cls()
        for sandbox_id in warm_ids:
            try:
                client = self._reconnect_client(sandbox_cls, sandbox_id)
            except Exception as e:
                logger.warning(
                    "Failed to reconnect warm-pool e2b sandbox %s for shutdown: %s",
                    sandbox_id,
                    e,
                )
                continue
            try:
                kill = getattr(client, "kill", None)
                if callable(kill):
                    kill()
            except Exception as e:
                logger.warning(
                    "Failed to kill warm-pool e2b sandbox %s during shutdown: %s",
                    sandbox_id,
                    e,
                )
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
