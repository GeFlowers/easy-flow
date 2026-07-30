"""提供按用户和线程隔离路径映射的本地沙箱提供者。"""
import logging
import threading
from collections import OrderedDict
from pathlib import Path

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider
from deerflow.skills.storage import user_should_see_legacy_skills

logger = logging.getLogger(__name__)

# Module-level alias kept for backward compatibility with older callers/tests
# that reach into ``local_sandbox_provider._singleton`` directly. New code reads
# the provider instance attributes (``_generic_sandbox`` / ``_thread_sandboxes``)
# instead.
_singleton: LocalSandbox | None = None

# Virtual prefixes that must be reserved by the per-thread mappings created in
# ``acquire`` — custom mounts from ``config.yaml`` may not overlap with these.
_USER_DATA_VIRTUAL_PREFIX = "/mnt/user-data"
_ACP_WORKSPACE_VIRTUAL_PREFIX = "/mnt/acp-workspace"

# Default upper bound on per-thread LocalSandbox instances retained in memory.
# Each cached instance is cheap (a small Python object with a list of
# PathMapping and a set of agent-written paths used for reverse resolve), but
# in a long-running gateway the number of distinct thread_ids is unbounded.
# When the cap is exceeded the least-recently-used entry is dropped; the next
# ``acquire(thread_id)`` for that thread simply rebuilds the sandbox at the
# cost of losing its accumulated ``_agent_written_paths`` (read_file falls
# back to no reverse resolution, which is the same behaviour as a fresh run).
DEFAULT_MAX_CACHED_THREAD_SANDBOXES = 256


class LocalSandboxProvider(SandboxProvider):
    """提供按用户和线程隔离路径映射的本地文件系统沙箱。

    有线程上下文时，为每个线程创建独立的 ``LocalSandbox``，把
    用户数据目录、智能体工作区和用户自定义技能映射到该用户、
    该线程的宿主目录；没有线程上下文的旧调用仍使用标识为 ``"local"`` 的通用实例。
    缓存操作由提供者级锁保护，并以 LRU 策略限制保留的线程沙箱数量。淘汰后仅会
    丢失智能体已写文件的反向路径解析提示，下一次获取会重建沙箱。
    """

    uses_thread_data_mounts = True
    needs_upload_permission_adjustment = False

    def __init__(self, max_cached_threads: int = DEFAULT_MAX_CACHED_THREAD_SANDBOXES):
        """使用静态路径映射初始化提供者，并设置线程沙箱 LRU 缓存上限。"""
        self._path_mappings = self._setup_path_mappings()
        self._generic_sandbox: LocalSandbox | None = None
        self._thread_sandboxes: OrderedDict[tuple[str, str], LocalSandbox] = OrderedDict()
        self._max_cached_threads = max_cached_threads
        self._lock = threading.Lock()

    def _setup_path_mappings(self) -> list[PathMapping]:
        """
        建立所有沙箱共享的静态路径映射。

        静态映射包含公共技能目录和配置中的自定义挂载；依赖线程或有效用户的
        用户数据目录、智能体工作区与自定义技能映射则在获取沙箱时追加。
        """
        mappings: list[PathMapping] = []

        # Map skills: split mount for public + legacy + custom
        try:
            from deerflow.config import get_app_config

            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            # Public skills: global, read-only — static, shared by all threads
            public_skills_path = skills_path / "public"
            if public_skills_path.exists():
                mappings.append(
                    PathMapping(
                        container_path=f"{container_path}/public",
                        local_path=str(public_skills_path),
                        read_only=True,
                    )
                )

            # NOTE: Legacy skills mount is NOT included here because it must
            # only be exposed to users who have no per-user custom skills yet
            # (mirroring ``UserScopedSkillStorage._iter_skill_files`` which only
            # surfaces SkillCategory.LEGACY to such users). Including it for
            # every user would let users with per-user custom skills still
            # ``read_file("/mnt/skills/legacy/<name>/SKILL.md")`` and read
            # content the listing layer told them doesn't exist. See review
            # feedback on PR #3889 — the legacy mount is now built in
            # ``_build_thread_path_mappings`` after we know the user_id.

            # NOTE: Custom skills mount is NOT included here because it is
            # per-user and must be built dynamically per-thread inside
            # ``_build_thread_path_mappings``.  The static mount that previously
            # bound ``get_effective_user_id()`` at init time was incorrect:
            # every subsequent user's sandbox would resolve
            # ``/mnt/skills/custom`` to the init-time user's directory.

            # Map custom mounts from sandbox config
            _RESERVED_CONTAINER_PREFIXES = [
                f"{container_path}/public",
                f"{container_path}/custom",
                f"{container_path}/legacy",
                _ACP_WORKSPACE_VIRTUAL_PREFIX,
                _USER_DATA_VIRTUAL_PREFIX,
            ]
            sandbox_config = config.sandbox
            if sandbox_config and sandbox_config.mounts:
                for mount in sandbox_config.mounts:
                    host_path = Path(mount.host_path)
                    container_path = mount.container_path.rstrip("/") or "/"

                    if not host_path.is_absolute():
                        logger.warning(
                            "Mount host_path must be absolute, skipping: %s -> %s",
                            mount.host_path,
                            mount.container_path,
                        )
                        continue

                    if not container_path.startswith("/"):
                        logger.warning(
                            "Mount container_path must be absolute, skipping: %s -> %s",
                            mount.host_path,
                            mount.container_path,
                        )
                        continue

                    # Reject mounts that conflict with reserved container paths
                    if any(container_path == p or container_path.startswith(p + "/") for p in _RESERVED_CONTAINER_PREFIXES):
                        logger.warning(
                            "Mount container_path conflicts with reserved prefix, skipping: %s",
                            mount.container_path,
                        )
                        continue
                    # Ensure the host path exists before adding mapping.
                    #
                    # ``host_path`` is resolved against the filesystem of the
                    # process running this provider — for ``make dev`` that is
                    # the host machine, but for ``make up`` it is the
                    # ``deer-flow-gateway`` container, so any host path that
                    # isn't bind-mounted into the gateway image will be missing
                    # here. Skipping silently makes this a high-cost-to-debug
                    # silent failure (sandbox skill / tool reads an empty dir
                    # instead of the configured mount), so escalate to ERROR
                    # and include actionable guidance. See #3244.
                    if host_path.exists():
                        mappings.append(
                            PathMapping(
                                container_path=container_path,
                                local_path=str(host_path.resolve()),
                                read_only=mount.read_only,
                            )
                        )
                    else:
                        logger.error(
                            "sandbox.mounts entry %s -> %s ignored: host_path %s does not exist from the "
                            "perspective of the gateway process. In Docker deployments (make up / docker-compose), "
                            "this path must also be bind-mounted into the gateway container — add a matching "
                            "volume entry under services.gateway.volumes in docker/docker-compose.yaml (and use "
                            "the in-container path here), or run in local mode (make dev) where the gateway sees "
                            "the host filesystem directly.",
                            mount.host_path,
                            mount.container_path,
                            mount.host_path,
                        )
        except Exception as e:
            # Log but don't fail if config loading fails
            logger.warning("Could not setup path mappings: %s", e, exc_info=True)

        return mappings

    @staticmethod
    def _effective_acquire_user_id(user_id: str | None) -> str:
        """返回显式用户标识；未提供时解析当前运行时的有效用户标识。"""
        from deerflow.runtime.user_context import get_effective_user_id

        return user_id or get_effective_user_id()

    @staticmethod
    def _thread_key(thread_id: str, user_id: str) -> tuple[str, str]:
        """构造用于线程沙箱缓存的用户与线程复合键。"""
        return (user_id, thread_id)

    @staticmethod
    def _sandbox_id_for_thread(thread_id: str, user_id: str) -> str:
        """构造包含用户和线程范围的本地沙箱标识。"""
        return f"local:{user_id}:{thread_id}"

    @staticmethod
    def _key_from_sandbox_id(sandbox_id: str) -> tuple[str, str] | None:
        """从本地线程沙箱标识解析用户与线程复合键。"""
        if not sandbox_id.startswith("local:"):
            return None
        value = sandbox_id[len("local:") :]
        user_id, separator, thread_id = value.partition(":")
        if not separator or not user_id or not thread_id:
            return None
        return (user_id, thread_id)

    @staticmethod
    def _build_thread_path_mappings(thread_id: str, *, user_id: str | None = None) -> list[PathMapping]:
        """建立线程级 ``/mnt/user-data``、工作区和用户技能路径映射。

        优先使用已解析的用户标识；未提供时兼容旧调用并从运行时取得。自定义技能以
        用户范围只读挂载，因为智能体通过宿主端的技能管理工具修改它们。
        """
        from deerflow.config import get_app_config
        from deerflow.config.paths import get_paths

        paths = get_paths()
        effective_user_id = LocalSandboxProvider._effective_acquire_user_id(user_id)
        paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)

        mappings = [
            # Aggregate parent mapping so ``ls /mnt/user-data`` and other
            # parent-level operations behave the same as inside AIO (where the
            # parent directory is real and contains the three subdirs). Longer
            # subpath mappings below still win for ``/mnt/user-data/workspace/...``
            # because ``_find_path_mapping`` sorts by container_path length.
            PathMapping(
                container_path=_USER_DATA_VIRTUAL_PREFIX,
                local_path=str(paths.sandbox_user_data_dir(thread_id, user_id=effective_user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/workspace",
                local_path=str(paths.sandbox_work_dir(thread_id, user_id=effective_user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/uploads",
                local_path=str(paths.sandbox_uploads_dir(thread_id, user_id=effective_user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/outputs",
                local_path=str(paths.sandbox_outputs_dir(thread_id, user_id=effective_user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=_ACP_WORKSPACE_VIRTUAL_PREFIX,
                local_path=str(paths.acp_workspace_dir(thread_id, user_id=effective_user_id)),
                read_only=False,
            ),
        ]

        # Per-user custom skills mount (read-only).  This must be per-thread
        # because ``/mnt/skills/custom`` resolves to different host directories
        # for different users.
        try:
            config = get_app_config()
            skills_container_path = config.skills.container_path
            user_custom_path = paths.user_custom_skills_dir(effective_user_id)
            user_custom_path.mkdir(parents=True, exist_ok=True)

            mappings.append(
                PathMapping(
                    container_path=f"{skills_container_path}/custom",
                    local_path=str(user_custom_path),
                    read_only=True,
                )
            )
        except Exception as exc:
            logger.warning("Could not setup per-thread custom skills mount: %s", exc, exc_info=True)

        # Legacy (pre-migration global-custom) skills: only mount for users
        # who have no per-user custom skills yet, mirroring the
        # ``UserScopedSkillStorage._iter_skill_files`` visibility rule. Users
        # with their own per-user custom skills cannot see LEGACY in the
        # listing/prompt and must not be able to read it via the sandbox
        # either — otherwise the listing layer and the sandbox layer disagree
        # about visibility, and the sandbox layer is the more permissive one.
        try:
            config = get_app_config()
            skills_container_path = config.skills.container_path
            user_custom_path = paths.user_custom_skills_dir(effective_user_id)
            legacy_skills_path = config.skills.get_skills_path() / "custom"
            if user_should_see_legacy_skills(effective_user_id, host_path=str(config.skills.get_skills_path())) and legacy_skills_path.exists():
                mappings.append(
                    PathMapping(
                        container_path=f"{skills_container_path}/legacy",
                        local_path=str(legacy_skills_path),
                        read_only=True,
                    )
                )
        except Exception as exc:
            logger.warning("Could not setup per-thread legacy skills mount: %s", exc, exc_info=True)

        return mappings

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """获取线程范围内的沙箱标识；没有线程时返回通用单例标识。

        缓存读取和插入受锁保护，相同用户和线程的并发调用始终得到同一实例；创建路径
        映射涉及文件系统访问时会临时释放锁，并在重新持锁后再次检查缓存。
        """
        global _singleton

        if thread_id is None:
            with self._lock:
                if self._generic_sandbox is None:
                    self._generic_sandbox = LocalSandbox("local", path_mappings=list(self._path_mappings))
                    _singleton = self._generic_sandbox
                return self._generic_sandbox.id

        effective_user_id = self._effective_acquire_user_id(user_id)
        key = self._thread_key(thread_id, effective_user_id)

        # Fast path under lock.
        with self._lock:
            cached = self._thread_sandboxes.get(key)
            if cached is not None:
                # Mark as most-recently used so frequently-touched threads
                # survive eviction.
                self._thread_sandboxes.move_to_end(key)
                return cached.id

        # ``_build_thread_path_mappings`` touches the filesystem
        # (``ensure_thread_dirs``); release the lock during I/O.
        new_mappings = list(self._path_mappings) + self._build_thread_path_mappings(thread_id, user_id=effective_user_id)

        with self._lock:
            # Re-check after the lock-free I/O: another caller may have
            # populated the cache while we were computing mappings.
            cached = self._thread_sandboxes.get(key)
            if cached is None:
                cached = LocalSandbox(self._sandbox_id_for_thread(thread_id, effective_user_id), path_mappings=new_mappings)
                self._thread_sandboxes[key] = cached
                self._evict_until_within_cap_locked()
            else:
                self._thread_sandboxes.move_to_end(key)
            return cached.id

    def _evict_until_within_cap_locked(self) -> None:
        """在缓存超过上限时按 LRU 策略淘汰线程沙箱；调用方必须持有锁。"""
        while len(self._thread_sandboxes) > self._max_cached_threads:
            evicted_key, _ = self._thread_sandboxes.popitem(last=False)
            logger.info(
                "Evicting LocalSandbox cache entry for user/thread %s/%s (cap=%d)",
                evicted_key[0],
                evicted_key[1],
                self._max_cached_threads,
            )

    def get(self, sandbox_id: str) -> Sandbox | None:
        """按标识获取通用或线程范围的本地沙箱，并更新线程缓存的使用顺序。"""
        if sandbox_id == "local":
            with self._lock:
                generic = self._generic_sandbox
            if generic is None:
                self.acquire()
                with self._lock:
                    return self._generic_sandbox
            return generic
        if isinstance(sandbox_id, str) and sandbox_id.startswith("local:"):
            key = self._key_from_sandbox_id(sandbox_id)
            if key is None:
                return None
            with self._lock:
                cached = self._thread_sandboxes.get(key)
                if cached is not None:
                    # Touching a thread via ``get`` (used by tools.py to look
                    # up the sandbox once per tool call) promotes it in LRU
                    # order so an active thread isn't evicted under load.
                    self._thread_sandboxes.move_to_end(key)
                return cached
        return None

    def release(self, sandbox_id: str) -> None:
        # LocalSandbox has no resources to release; keep the cached instance so
        # that ``_agent_written_paths`` (used to reverse-resolve agent-authored
        # file contents on read) survives between turns. LRU eviction in
        # ``acquire`` and explicit ``reset()`` / ``shutdown()`` are the only
        # paths that drop cached entries.
        #
        # Note: This method is intentionally not called by SandboxMiddleware
        # to allow sandbox reuse across multiple turns in a thread.
        """保留本地沙箱缓存；其资源由 LRU 淘汰、重置或关闭统一回收。"""
        pass

    def reset(self) -> None:
        """清空所有本地沙箱缓存，使后续获取应用新的配置和挂载。"""
        global _singleton
        with self._lock:
            self._generic_sandbox = None
            self._thread_sandboxes.clear()
            _singleton = None

    def shutdown(self) -> None:
        # LocalSandboxProvider has no extra resources beyond the cached
        # ``LocalSandbox`` instances, so shutdown uses the same cleanup path
        # as ``reset``.
        """关闭提供者；本地实现复用重置逻辑清理缓存。"""
        self.reset()
