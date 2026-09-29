"""统一编排本机或远端沙箱后端，负责实例缓存、线程隔离、挂载与生命周期管理。"""

import asyncio
import atexit
import hashlib
import logging
import os
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]
    import msvcrt

from deerflow.community.warm_pool_lifecycle import (
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_REPLICAS,
    WarmPoolLifecycleMixin,
)
from deerflow.community.warm_pool_lifecycle import (
    IDLE_CHECK_INTERVAL as _SHARED_IDLE_CHECK_INTERVAL,
)
from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths, join_host_path
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider
from deerflow.skills.storage import user_should_see_legacy_skills

from .aio_sandbox import AioSandbox
from .backend import SandboxBackend, wait_for_sandbox_ready, wait_for_sandbox_ready_async
from .local_backend import LocalContainerBackend
from .remote_backend import RemoteSandboxBackend
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
DEFAULT_PORT = 8080
DEFAULT_CONTAINER_PREFIX = "deer-flow-sandbox"
IDLE_CHECK_INTERVAL = _SHARED_IDLE_CHECK_INTERVAL
THREAD_LOCK_EXECUTOR_WORKERS = min(32, (os.cpu_count() or 1) + 4)
_THREAD_LOCK_EXECUTOR = ThreadPoolExecutor(max_workers=THREAD_LOCK_EXECUTOR_WORKERS, thread_name_prefix="sandbox-lock-wait")
atexit.register(_THREAD_LOCK_EXECUTOR.shutdown, wait=False, cancel_futures=True)


def _lock_file_exclusive(lock_file) -> None:
    """按当前操作系统使用 POSIX 或 Windows 文件锁独占锁文件。"""
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return

    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_file(lock_file) -> None:
    """释放由对应平台文件锁 API 建立的独占锁。"""
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        return

    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _open_lock_file(lock_path):
    """打开跨进程沙箱协调锁文件，供异步路径在线程池中调用。"""
    return open(lock_path, "a", encoding="utf-8")


async def _acquire_thread_lock_async(lock: threading.Lock) -> None:
    """在线程池等待线程锁，避免阻塞事件循环，并在协程取消后安排锁释放。"""
    loop = asyncio.get_running_loop()
    acquire_future = loop.run_in_executor(_THREAD_LOCK_EXECUTOR, lock.acquire, True)

    try:
        acquired = await asyncio.shield(acquire_future)
    except asyncio.CancelledError:
        acquire_future.add_done_callback(lambda task: _release_cancelled_lock_acquire(lock, task))
        raise

    if not acquired:
        raise RuntimeError("Failed to acquire sandbox thread lock")


def _release_cancelled_lock_acquire(lock: threading.Lock, task: asyncio.Future[bool]) -> None:
    """等待任务在取消后才取得锁时释放锁，避免锁被遗留占用。"""
    if task.cancelled():
        return

    try:
        acquired = task.result()
    except Exception as e:
        logger.warning(f"Cancelled sandbox lock acquisition finished with error: {e}")
        return

    if acquired:
        lock.release()


class AioSandboxProvider(WarmPoolLifecycleMixin[SandboxInfo], SandboxProvider):
    """协调 SandboxBackend 与沙箱缓存，提供用户线程隔离的创建、复用和回收入口。"""

    def __init__(self):
        """初始化活动和预热状态，加载配置、选择后端并恢复遗留容器。"""
        self._lock = threading.Lock()
        self._sandboxes: dict[str, AioSandbox] = {}  # sandbox_id -> AioSandbox instance
        self._sandbox_infos: dict[str, SandboxInfo] = {}  # sandbox_id -> SandboxInfo (for destroy)
        self._thread_sandboxes: dict[tuple[str, str], str] = {}  # (user_id, thread_id) -> sandbox_id
        self._thread_locks: dict[tuple[str, str], threading.Lock] = {}  # (user_id, thread_id) -> in-process lock
        self._last_activity: dict[str, float] = {}  # sandbox_id -> last activity timestamp
        # Warm pool: released sandboxes whose containers are still running.
        # Maps sandbox_id -> (SandboxInfo, release_timestamp).
        # Containers here can be reclaimed quickly (no cold-start) or destroyed
        # when replicas capacity is exhausted.
        self._warm_pool: dict[str, tuple[SandboxInfo, float]] = {}
        self._shutdown_called = False
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None

        self._config = self._load_config()
        self._backend: SandboxBackend = self._create_backend()

        # 进程退出时释放活动与预热实例。
        atexit.register(self.shutdown)
        self._register_signal_handlers()

        # 接管上次进程遗留的容器，避免重启后孤儿资源持续运行。
        self._reconcile_orphans()

        # 只有配置启用空闲回收时才启动后台巡检。
        if self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT) > 0:
            self._start_idle_checker()

    @property
    def uses_thread_data_mounts(self) -> bool:
        """本机容器把线程目录作为挂载直接共享；远端后端可能需要显式同步文件。"""
        return isinstance(self._backend, LocalContainerBackend)

    # ── Factory methods ──────────────────────────────────────────────────

    def _create_backend(self) -> SandboxBackend:
        """配置了 Provisioner 地址时创建远端后端，否则创建本地容器后端。"""
        provisioner_url = self._config.get("provisioner_url")
        if provisioner_url:
            logger.info(f"Using remote sandbox backend with provisioner at {provisioner_url}")
            api_key = self._config.get("provisioner_api_key", "")
            return RemoteSandboxBackend(provisioner_url=provisioner_url, api_key=api_key)

        logger.info("Using local container sandbox backend")
        return LocalContainerBackend(
            image=self._config["image"],
            base_port=self._config["port"],
            container_prefix=self._config["container_prefix"],
            config_mounts=self._config["mounts"],
            environment=self._config["environment"],
        )

    # ── Configuration ────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        """从应用配置读取镜像、端口、挂载、环境变量和资源回收参数。"""
        config = get_app_config()
        sandbox_config = config.sandbox

        idle_timeout = getattr(sandbox_config, "idle_timeout", None)
        replicas = getattr(sandbox_config, "replicas", None)

        return {
            "image": sandbox_config.image or DEFAULT_IMAGE,
            "port": sandbox_config.port or DEFAULT_PORT,
            "container_prefix": sandbox_config.container_prefix or DEFAULT_CONTAINER_PREFIX,
            "idle_timeout": idle_timeout if idle_timeout is not None else DEFAULT_IDLE_TIMEOUT,
            "replicas": replicas if replicas is not None else DEFAULT_REPLICAS,
            "mounts": sandbox_config.mounts or [],
            "environment": self._resolve_env_vars(sandbox_config.environment or {}),
            # 配置后端 Pod 生命周期代理服务。
            "provisioner_url": getattr(sandbox_config, "provisioner_url", None) or "",
            "provisioner_api_key": getattr(sandbox_config, "provisioner_api_key", None) or "",
        }

    @staticmethod
    def _resolve_env_vars(env_config: dict[str, str]) -> dict[str, str]:
        """将以美元符号开头的配置值替换为对应环境变量内容。"""
        resolved = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                env_name = value[1:]
                resolved[key] = os.environ.get(env_name, "")
            else:
                resolved[key] = str(value)
        return resolved

    # ── Startup reconciliation ────────────────────────────────────────────

    def _reconcile_orphans(self) -> None:
        """启动时将后端发现的实例纳入预热池，由空闲回收器判定何时可以销毁。"""
        try:
            running = self._backend.list_running()
        except Exception as e:
            logger.warning(f"Failed to enumerate running containers during startup reconciliation: {e}")
            return

        if not running:
            return

        current_time = time.time()
        adopted = 0

        for info in running:
            age = current_time - info.created_at if info.created_at > 0 else float("inf")
            # 在同一个锁区间内检查并插入，避免并发启动重复认领同一容器。
            with self._lock:
                if info.sandbox_id in self._sandboxes or info.sandbox_id in self._warm_pool:
                    continue
                self._warm_pool[info.sandbox_id] = (info, current_time)
            adopted += 1
            logger.info(f"Adopted container {info.sandbox_id} into warm pool (age: {age:.0f}s)")

        logger.info(f"Startup reconciliation complete: {adopted} adopted into warm pool, {len(running)} total found")

    # ── Deterministic ID ─────────────────────────────────────────────────

    @staticmethod
    def _effective_acquire_user_id(user_id: str | None) -> str:
        """优先使用调用方用户 ID，否则解析当前执行上下文的有效用户。"""
        return user_id or get_effective_user_id()

    @staticmethod
    def _thread_key(thread_id: str, user_id: str) -> tuple[str, str]:
        """构造用户和线程联合键，避免不同用户的同名线程共享沙箱。"""
        return (user_id, thread_id)

    @staticmethod
    def _deterministic_sandbox_id(thread_id: str, user_id: str) -> str:
        """由用户和线程计算稳定沙箱 ID，确保不同数据桶不能复用同一实例。"""
        return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:8]

    # ── Mount helpers ────────────────────────────────────────────────────

    def _get_extra_mounts(self, thread_id: str | None, *, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """合并线程数据目录挂载和当前用户可见的技能目录挂载。"""
        mounts: list[tuple[str, str, bool]] = []

        if thread_id:
            mounts.extend(self._get_thread_mounts(thread_id, user_id=user_id))
            logger.info(f"Adding thread mounts for thread {thread_id}: {mounts}")

        skills_mounts = self._get_skills_mounts(user_id=user_id)
        if skills_mounts:
            mounts.extend(skills_mounts)
            logger.info(f"Adding skills mounts: {skills_mounts}")

        return mounts

    @staticmethod
    def _get_thread_mounts(thread_id: str, *, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """确保线程工作区目录存在，并返回工作区、上传、输出和只读 ACP 挂载。"""
        paths = get_paths()
        effective_user_id = AioSandboxProvider._effective_acquire_user_id(user_id)
        paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)

        return [
            (paths.host_sandbox_work_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/workspace", False),
            (paths.host_sandbox_uploads_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/uploads", False),
            (paths.host_sandbox_outputs_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/outputs", False),
            # ACP 子进程在宿主机写入，Agent 只需在沙箱内读取结果。
            (paths.host_acp_workspace_dir(thread_id, user_id=effective_user_id), "/mnt/acp-workspace", True),
        ]

    @staticmethod
    def _get_skills_mounts(*, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """把公共、自定义和兼容旧目录技能分别挂载到容器内对应类别目录。"""
        mounts: list[tuple[str, str, bool]] = []
        try:
            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            # When running inside Docker with DooD, use host-side skills path.
            host_skills_root = os.environ.get("DEER_FLOW_HOST_SKILLS_PATH") or str(skills_path)

            # 1. Public skills: global, read-only — static, shared by all threads
            public_skills_path = skills_path / "public"
            if public_skills_path.exists():
                mounts.append(
                    (
                        join_host_path(host_skills_root, "public"),
                        f"{container_path}/public",
                        True,
                    )
                )

            # 2. Per-user custom skills: read-only, per-thread/per-user
            effective_user_id = AioSandboxProvider._effective_acquire_user_id(user_id)
            paths = get_paths()
            user_custom_path = paths.user_custom_skills_dir(effective_user_id)
            user_custom_path.mkdir(parents=True, exist_ok=True)

            host_user_custom = join_host_path(
                str(paths.host_base_dir),
                "users",
                effective_user_id,
                "skills",
                "custom",
            )
            mounts.append(
                (
                    host_user_custom,
                    f"{container_path}/custom",
                    True,
                )
            )

            # 3. Legacy (pre-migration global-custom) skills: only mount for
            #    users who have no per-user custom skills yet, mirroring
            #    ``UserScopedSkillStorage._iter_skill_files`` visibility rule.
            legacy_skills_path = skills_path / "custom"
            if user_should_see_legacy_skills(effective_user_id, host_path=str(skills_path)) and legacy_skills_path.exists():
                mounts.append(
                    (
                        join_host_path(host_skills_root, "custom"),
                        f"{container_path}/legacy",
                        True,
                    )
                )
        except Exception as e:
            logger.warning("Could not setup skills mounts: %s", e)

        return mounts

    # ── Idle timeout management ──────────────────────────────────────────

    def _cleanup_idle_resources(self, idle_timeout: float) -> None:
        """委托沙箱专属清理逻辑回收超时的活动或预热实例。"""
        self._cleanup_idle_sandboxes(idle_timeout)

    def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
        """销毁超时的活动实例并回收过期预热项；销毁前重新确认空闲状态。"""
        current_time = time.time()
        active_to_destroy = []

        with self._lock:
            # 活动实例以最后访问时间判断是否空闲。
            for sandbox_id, last_activity in self._last_activity.items():
                idle_duration = current_time - last_activity
                if idle_duration > idle_timeout:
                    active_to_destroy.append(sandbox_id)
                    logger.info(f"Sandbox {sandbox_id} idle for {idle_duration:.1f}s, marking for destroy")

        # 销毁前再次检查，防止快照后实例已被重新获取。
        for sandbox_id in active_to_destroy:
            try:
                # 快照与销毁之间可能发生重新获取或释放，因此锁内复核状态。
                with self._lock:
                    last_activity = self._last_activity.get(sandbox_id)
                    if last_activity is None:
                        # 已由其他路径释放或销毁。
                        logger.info(f"Sandbox {sandbox_id} already gone before idle destroy, skipping")
                        continue
                    if (time.time() - last_activity) < idle_timeout:
                        # 快照后被重新获取，更新时间已变化。
                        logger.info(f"Sandbox {sandbox_id} was re-acquired before idle destroy, skipping")
                        continue
                logger.info(f"Destroying idle sandbox {sandbox_id}")
                self.destroy(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to destroy idle sandbox {sandbox_id}: {e}")

        self._reap_expired_warm(idle_timeout)

    # ── Signal handling ──────────────────────────────────────────────────

    def _register_signal_handlers(self) -> None:
        """为终止、键盘中断和终端挂断信号注册清理处理器，并保留原处理方式。"""
        self._original_sigterm = signal.getsignal(signal.SIGTERM)
        self._original_sigint = signal.getsignal(signal.SIGINT)
        self._original_sighup = signal.getsignal(signal.SIGHUP) if hasattr(signal, "SIGHUP") else None

        def signal_handler(signum, frame):
            """清理沙箱后转交信号给原处理器，保留进程原有终止行为。"""
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

        try:
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
            if hasattr(signal, "SIGHUP"):
                signal.signal(signal.SIGHUP, signal_handler)
        except ValueError:
            logger.debug("Could not register signal handlers (not main thread)")

    # ── Thread locking (in-process) ──────────────────────────────────────

    def _get_thread_lock(self, thread_id: str, user_id: str) -> threading.Lock:
        """获取或创建用户线程级互斥锁，串行化本进程内的同线程沙箱获取。"""
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            if key not in self._thread_locks:
                self._thread_locks[key] = threading.Lock()
            return self._thread_locks[key]

    def _sandbox_id_for_thread(self, thread_id: str | None, user_id: str | None) -> str:
        """有线程 ID 时返回稳定沙箱 ID；匿名调用则生成随机 ID。"""
        return self._deterministic_sandbox_id(thread_id, self._effective_acquire_user_id(user_id)) if thread_id else str(uuid.uuid4())[:8]

    def _reuse_in_process_sandbox(self, thread_id: str | None, *, user_id: str | None = None, post_lock: bool = False) -> str | None:
        """复用本进程缓存的活动实例；健康检查确认失效时清理缓存并返回空值。"""
        if thread_id is None:
            return None

        effective_user_id = self._effective_acquire_user_id(user_id)
        key = self._thread_key(thread_id, effective_user_id)
        with self._lock:
            if key not in self._thread_sandboxes:
                return None

            existing_id = self._thread_sandboxes[key]
            if existing_id in self._sandboxes:
                info = self._sandbox_infos.get(existing_id)
            else:
                del self._thread_sandboxes[key]
                return None

        alive = self._check_tracked_sandbox_alive(existing_id, info) if info is not None else True
        if alive is False:
            self._drop_unhealthy_sandbox(
                existing_id,
                "in-process cache failed health check",
                expected_info=info,
            )
            return None

        with self._lock:
            if self._thread_sandboxes.get(key) != existing_id:
                return None
            if existing_id not in self._sandboxes:
                self._thread_sandboxes.pop(key, None)
                return None

            suffix = " (post-lock check)" if post_lock else ""
            logger.info(f"Reusing in-process sandbox {existing_id} for user/thread {effective_user_id}/{thread_id}{suffix}")
            self._last_activity[existing_id] = time.time()
            return existing_id

    def _reclaim_warm_pool_sandbox(
        self,
        thread_id: str | None,
        sandbox_id: str,
        *,
        user_id: str | None = None,
        post_lock: bool = False,
    ) -> str | None:
        """健康检查预热实例后将其移回活动映射，并恢复线程到实例的关联。"""
        if thread_id is None:
            return None

        effective_user_id = self._effective_acquire_user_id(user_id)
        key = self._thread_key(thread_id, effective_user_id)
        with self._lock:
            if sandbox_id not in self._warm_pool:
                return None

            info, _ = self._warm_pool[sandbox_id]

        alive = self._check_tracked_sandbox_alive(sandbox_id, info)
        if alive is False:
            self._drop_unhealthy_sandbox(
                sandbox_id,
                "warm-pool cache failed health check",
                expected_info=info,
            )
            return None

        with self._lock:
            warm_item = self._warm_pool.pop(sandbox_id, None)
            if warm_item is None:
                return None
            info, _ = warm_item
            sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._last_activity[sandbox_id] = time.time()
            self._thread_sandboxes[key] = sandbox_id

        suffix = " (post-lock check)" if post_lock else f" at {info.sandbox_url}"
        logger.info(f"Reclaimed warm-pool sandbox {sandbox_id} for user/thread {effective_user_id}/{thread_id}{suffix}")
        return sandbox_id

    def _recheck_cached_sandbox(self, thread_id: str, sandbox_id: str, *, user_id: str) -> str | None:
        """获得跨进程锁后再次检查活动缓存和预热池，避免重复发现或创建。"""
        return self._reuse_in_process_sandbox(thread_id, user_id=user_id, post_lock=True) or self._reclaim_warm_pool_sandbox(
            thread_id,
            sandbox_id,
            user_id=user_id,
            post_lock=True,
        )

    def _register_discovered_sandbox(self, thread_id: str, info: SandboxInfo, *, user_id: str) -> str:
        """将后端发现的实例登记为活动沙箱，并绑定到用户线程。"""
        sandbox = AioSandbox(id=info.sandbox_id, base_url=info.sandbox_url)
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            self._sandboxes[info.sandbox_id] = sandbox
            self._sandbox_infos[info.sandbox_id] = info
            self._last_activity[info.sandbox_id] = time.time()
            self._thread_sandboxes[key] = info.sandbox_id

        logger.info(f"Discovered existing sandbox {info.sandbox_id} for user/thread {user_id}/{thread_id} at {info.sandbox_url}")
        return info.sandbox_id

    def _register_created_sandbox(self, thread_id: str | None, sandbox_id: str, info: SandboxInfo, *, user_id: str | None = None) -> str:
        """将新建实例写入活动映射，记录访问时间并建立线程关联。"""
        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._last_activity[sandbox_id] = time.time()
            if thread_id:
                self._thread_sandboxes[self._thread_key(thread_id, self._effective_acquire_user_id(user_id))] = sandbox_id

        logger.info(f"Created sandbox {sandbox_id} for thread {thread_id} at {info.sandbox_url}")
        return sandbox_id

    def _check_tracked_sandbox_alive(self, sandbox_id: str, info: SandboxInfo) -> bool | None:
        """查询后端健康状态；检查本身失败时返回未知值，不误判实例已死亡。"""
        try:
            return self._backend.is_alive(info)
        except Exception as e:
            logger.warning(f"Failed to check sandbox {sandbox_id} health: {e}")
            return None

    def _remove_tracked_sandbox(
        self,
        sandbox_id: str,
        *,
        expected_info: SandboxInfo | None = None,
    ) -> tuple[Sandbox | None, SandboxInfo | None, bool]:
        """从活动、预热和线程映射中移除实例；可用对象身份检查防止旧健康结果误删新实例。"""
        thread_keys_to_remove: list[tuple[str, str]] = []

        with self._lock:
            active_info = self._sandbox_infos.get(sandbox_id)
            warm_item = self._warm_pool.get(sandbox_id)
            warm_info = warm_item[0] if warm_item is not None else None
            if expected_info is not None and active_info is not expected_info and warm_info is not expected_info:
                return None, None, False

            sandbox = self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_keys_to_remove = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in thread_keys_to_remove:
                del self._thread_sandboxes[key]
            self._last_activity.pop(sandbox_id, None)
            if info is None and sandbox_id in self._warm_pool:
                info, _ = self._warm_pool.pop(sandbox_id)
            else:
                self._warm_pool.pop(sandbox_id, None)

        return sandbox, info, True

    def _drop_unhealthy_sandbox(self, sandbox_id: str, reason: str, *, expected_info: SandboxInfo | None = None) -> None:
        """确认实例失效后移除所有跟踪并关闭客户端和底层容器。"""
        sandbox, info, removed = self._remove_tracked_sandbox(sandbox_id, expected_info=expected_info)
        if not removed:
            logger.info(f"Skipped dropping sandbox {sandbox_id}: tracked info changed after health check")
            return

        if sandbox is not None:
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing unhealthy sandbox {sandbox_id}: {e}")

        if info is not None:
            try:
                self._backend.destroy(info)
            except Exception as e:
                logger.warning(f"Error destroying unhealthy sandbox {sandbox_id}: {e}")

        logger.warning(f"Dropped unhealthy sandbox {sandbox_id}: {reason}")

    def _active_count_locked(self) -> int:
        """在持有状态锁时返回当前活动沙箱数量。"""
        return len(self._sandboxes)

    def _destroy_warm_entry(self, sandbox_id: str, entry: SandboxInfo, *, reason: str) -> None:
        """销毁已从预热池移除的实例，并根据回收原因记录结果。"""
        try:
            self._backend.destroy(entry)
        except Exception as e:
            if reason == "idle_timeout":
                logger.error(f"Failed to destroy idle warm-pool sandbox {sandbox_id}: {e}")
            elif reason == "replica_enforcement":
                logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id}: {e}")
            else:
                logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id} for {reason}: {e}")
            return

        if reason == "idle_timeout":
            logger.info(f"Destroyed idle warm-pool sandbox {sandbox_id}")
        elif reason == "replica_enforcement":
            logger.info(f"Destroyed warm-pool sandbox {sandbox_id}")
        else:
            logger.info(f"Destroyed warm-pool sandbox {sandbox_id} for {reason}")

    # ── Core: acquire / get / release / shutdown ─────────────────────────

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """获取线程对应的沙箱；同一用户和线程会复用稳定标识的实例。

        Args:
            thread_id: 用于隔离沙箱和挂载线程数据的会话标识；为空时创建匿名沙箱。
            user_id: 沙箱所属用户标识；未提供时采用当前请求上下文中的用户。

        Returns:
            已获取沙箱的标识。
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        if thread_id:
            thread_lock = self._get_thread_lock(thread_id, effective_user_id)
            with thread_lock:
                return self._acquire_internal(thread_id, user_id=effective_user_id)
        else:
            return self._acquire_internal(thread_id, user_id=effective_user_id)

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """以异步方式获取沙箱，避免等待锁、容器操作或就绪检查时阻塞事件循环。

        参数和复用规则与 ``acquire`` 相同。
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        if thread_id:
            thread_lock = self._get_thread_lock(thread_id, effective_user_id)
            await _acquire_thread_lock_async(thread_lock)
            try:
                return await self._acquire_internal_async(thread_id, user_id=effective_user_id)
            finally:
                thread_lock.release()

        return await self._acquire_internal_async(thread_id, user_id=effective_user_id)

    def _acquire_internal(self, thread_id: str | None, *, user_id: str) -> str:
        """按进程内缓存、预热池、后端发现的顺序复用沙箱，找不到时才创建实例。"""
        cached_id = self._reuse_in_process_sandbox(thread_id, user_id=user_id)
        if cached_id is not None:
            return cached_id

        # 线程沙箱使用稳定标识，匿名调用则生成随机标识。
        sandbox_id = self._sandbox_id_for_thread(thread_id, user_id)

        # 优先从仍在运行的预热池取回实例，避免容器冷启动。
        reclaimed_id = self._reclaim_warm_pool_sandbox(thread_id, sandbox_id, user_id=user_id)
        if reclaimed_id is not None:
            return reclaimed_id

        # 文件锁串行化多进程创建；后到进程可发现先到进程已启动的容器。
        if thread_id:
            return self._discover_or_create_with_lock(thread_id, sandbox_id, user_id=user_id)

        return self._create_sandbox(thread_id, sandbox_id, user_id=user_id)

    async def _acquire_internal_async(self, thread_id: str | None, *, user_id: str) -> str:
        """异步执行缓存、预热池、后端发现和创建流程，与同步版本保持相同的复用规则。"""
        cached_id = await asyncio.to_thread(self._reuse_in_process_sandbox, thread_id, user_id=user_id)
        if cached_id is not None:
            return cached_id

        # 线程沙箱使用稳定标识，匿名调用则生成随机标识。
        sandbox_id = self._sandbox_id_for_thread(thread_id, user_id)

        # 优先从仍在运行的预热池取回实例，避免容器冷启动。
        reclaimed_id = await asyncio.to_thread(self._reclaim_warm_pool_sandbox, thread_id, sandbox_id, user_id=user_id)
        if reclaimed_id is not None:
            return reclaimed_id

        # 线程沙箱的发现和创建由跨进程文件锁保护。
        if thread_id:
            return await self._discover_or_create_with_lock_async(thread_id, sandbox_id, user_id=user_id)

        return await self._create_sandbox_async(thread_id, sandbox_id, user_id=user_id)

    def _discover_or_create_with_lock(self, thread_id: str, sandbox_id: str, *, user_id: str | None = None) -> str:
        """在跨进程文件锁内再次检查缓存、发现已有容器，或创建并登记新沙箱。"""
        paths = get_paths()
        effective_user_id = self._effective_acquire_user_id(user_id)
        paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)
        lock_path = paths.thread_dir(thread_id, user_id=effective_user_id) / f"{sandbox_id}.lock"

        with open(lock_path, "a", encoding="utf-8") as lock_file:
            locked = False
            try:
                _lock_file_exclusive(lock_file)
                locked = True
                # 等待文件锁期间进程内可能已有其他线程完成创建，因此再次检查缓存。
                cached_id = self._recheck_cached_sandbox(thread_id, sandbox_id, user_id=effective_user_id)
                if cached_id is not None:
                    return cached_id

                # 其他进程可能已经创建容器，先向后端查询以避免重名创建。
                discovered = self._backend.discover(sandbox_id)
                if discovered is not None:
                    return self._register_discovered_sandbox(thread_id, discovered, user_id=effective_user_id)

                return self._create_sandbox(thread_id, sandbox_id, user_id=effective_user_id)
            finally:
                if locked:
                    _unlock_file(lock_file)

    async def _discover_or_create_with_lock_async(self, thread_id: str, sandbox_id: str, *, user_id: str | None = None) -> str:
        """异步持有跨进程文件锁，并在线程池中执行阻塞的目录、锁和后端操作。"""
        paths = get_paths()
        effective_user_id = self._effective_acquire_user_id(user_id)
        await asyncio.to_thread(paths.ensure_thread_dirs, thread_id, user_id=effective_user_id)
        lock_path = paths.thread_dir(thread_id, user_id=effective_user_id) / f"{sandbox_id}.lock"

        lock_file = await asyncio.to_thread(_open_lock_file, lock_path)
        locked = False
        try:
            await asyncio.to_thread(_lock_file_exclusive, lock_file)
            locked = True
            # 等待文件锁期间进程内可能已有其他线程完成创建，因此再次检查缓存。
            cached_id = await asyncio.to_thread(self._recheck_cached_sandbox, thread_id, sandbox_id, user_id=effective_user_id)
            if cached_id is not None:
                return cached_id

            # 本地发现可能检查 Docker 并执行健康探测，放到工作线程避免阻塞事件循环。
            discovered = await asyncio.to_thread(self._backend.discover, sandbox_id)
            if discovered is not None:
                return self._register_discovered_sandbox(thread_id, discovered, user_id=effective_user_id)

            return await self._create_sandbox_async(thread_id, sandbox_id, user_id=effective_user_id)
        finally:
            if locked:
                await asyncio.to_thread(_unlock_file, lock_file)
            await asyncio.to_thread(lock_file.close)

    def _create_sandbox(self, thread_id: str | None, sandbox_id: str, *, user_id: str | None = None) -> str:
        """创建后端沙箱、等待服务就绪，并将实例登记到活动沙箱表。

        Args:
            thread_id: 沙箱关联的线程标识；匿名沙箱传入 ``None``。
            sandbox_id: 预先计算的沙箱标识。
            user_id: 沙箱所属用户标识。

        Raises:
            RuntimeError: 沙箱在限定时间内未就绪。
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        extra_mounts = self._get_extra_mounts(thread_id, user_id=effective_user_id)

        # 容量不足时只淘汰预热实例；正在被线程使用的活动沙箱不能强制停止。
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        info = self._backend.create(thread_id, sandbox_id, extra_mounts=extra_mounts or None, user_id=effective_user_id)

        # 服务未就绪时回收刚创建的容器并报告失败。
        if not wait_for_sandbox_ready(info.sandbox_url, timeout=60):
            self._backend.destroy(info)
            raise RuntimeError(f"Sandbox {sandbox_id} failed to become ready within timeout at {info.sandbox_url}")

        return self._register_created_sandbox(thread_id, sandbox_id, info, user_id=effective_user_id)

    async def _create_sandbox_async(self, thread_id: str | None, sandbox_id: str, *, user_id: str | None = None) -> str:
        """在线程池中完成阻塞创建操作，并异步等待服务就绪后登记沙箱。"""
        effective_user_id = self._effective_acquire_user_id(user_id)
        extra_mounts = await asyncio.to_thread(self._get_extra_mounts, thread_id, user_id=effective_user_id)

        # 容量不足时只淘汰预热实例；正在被线程使用的活动沙箱不能强制停止。
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = await asyncio.to_thread(self._evict_oldest_warm)
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        info = await asyncio.to_thread(self._backend.create, thread_id, sandbox_id, extra_mounts=extra_mounts or None, user_id=effective_user_id)

        # 使用异步探测等待就绪；超时则释放刚创建的容器。
        if not await wait_for_sandbox_ready_async(info.sandbox_url, timeout=60):
            await asyncio.to_thread(self._backend.destroy, info)
            raise RuntimeError(f"Sandbox {sandbox_id} failed to become ready within timeout at {info.sandbox_url}")

        return self._register_created_sandbox(thread_id, sandbox_id, info, user_id=effective_user_id)

    def get(self, sandbox_id: str) -> Sandbox | None:
        """按标识查找活动沙箱；找到时刷新最后活动时间，供空闲回收判断。"""
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is not None:
                self._last_activity[sandbox_id] = time.time()
            return sandbox

    def release(self, sandbox_id: str) -> None:
        """结束活动租用并将容器转入预热池，保留运行中的环境供后续快速复用。

        释放缓存的沙箱对象及其 HTTP 客户端，但不停止容器；容器由容量淘汰或关闭流程回收。
        """
        info = None
        sandbox = None
        thread_keys_to_remove: list[tuple[str, str]] = []

        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_keys_to_remove = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in thread_keys_to_remove:
                del self._thread_sandboxes[key]
            self._last_activity.pop(sandbox_id, None)
            # 仅移出活动表，容器仍运行并进入预热池。
            if info and sandbox_id not in self._warm_pool:
                self._warm_pool[sandbox_id] = (info, time.time())

        if sandbox is not None:
            # 即使对象关闭异常，也不能阻止容器转入预热池。
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {sandbox_id} during release: {e}")

        logger.info(f"Released sandbox {sandbox_id} to warm pool (container still running)")

    def destroy(self, sandbox_id: str) -> None:
        """从跟踪表移除沙箱并停止后端容器，同时关闭缓存对象持有的网络客户端。
        """
        sandbox, info, _ = self._remove_tracked_sandbox(sandbox_id)

        if sandbox is not None:
            # 客户端关闭失败不应中断容器销毁。
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {sandbox_id} during destroy: {e}")

        if info:
            self._backend.destroy(info)
            logger.info(f"Destroyed sandbox {sandbox_id}")

    def shutdown(self) -> None:
        """停止空闲检查器并销毁活动和预热沙箱；重复调用不会重复执行关闭流程。"""
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            sandbox_ids = list(self._sandboxes.keys())
            warm_items = list(self._warm_pool.items())
            self._warm_pool.clear()

        self._stop_idle_checker()

        logger.info(f"Shutting down {len(sandbox_ids)} active + {len(warm_items)} warm-pool sandbox(es)")

        for sandbox_id in sandbox_ids:
            try:
                self.destroy(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to destroy sandbox {sandbox_id} during shutdown: {e}")

        for sandbox_id, (info, _) in warm_items:
            try:
                self._backend.destroy(info)
                logger.info(f"Destroyed warm-pool sandbox {sandbox_id} during shutdown")
            except Exception as e:
                logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id} during shutdown: {e}")
