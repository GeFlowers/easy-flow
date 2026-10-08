'''集中解析 DeerFlow 数据根目录，并生成用户、线程和沙箱数据路径。'''

import hashlib
import logging
import os
import re
import shutil
from pathlib import Path, PureWindowsPath

from deerflow.config.runtime_paths import runtime_home

VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_UNSAFE_USER_ID_CHAR_RE = re.compile(r"[^A-Za-z0-9_\-]")
_SAFE_USER_ID_DIGEST_HEX_LEN = 16

logger = logging.getLogger(__name__)


def _default_local_base_dir() -> Path:
    '''返回本地运行时目录；容器部署时该目录来自 ``DEER_FLOW_HOME`` 的默认策略。'''
    return runtime_home()


def _validate_thread_id(thread_id: str) -> str:
    '''只允许安全字符组成的线程标识进入磁盘路径，避免路径穿越。'''
    if not _SAFE_THREAD_ID_RE.match(thread_id):
        raise ValueError(f"Invalid thread_id {thread_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return thread_id


def _validate_user_id(user_id: str) -> str:
    '''校验已规范化的用户标识，防止其改变用户数据目录层级。'''
    if not _SAFE_USER_ID_RE.match(user_id):
        raise ValueError(f"Invalid user_id {user_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return user_id


def make_safe_user_id(raw: str) -> str:
    '''把外部用户标识转成文件系统安全名称，并以摘要区分规范化冲突。'''
    if not raw:
        raise ValueError("user_id must be a non-empty string.")
    sanitized = _UNSAFE_USER_ID_CHAR_RE.sub("-", raw)
    if sanitized == raw:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_SAFE_USER_ID_DIGEST_HEX_LEN]
    return f"{sanitized}-{digest}"


def _legacy_safe_user_id(raw: str, sanitized: str) -> str:
    '''按旧版摘要规则生成目录名，以便升级时定位并迁移历史用户目录。'''
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:_SAFE_USER_ID_DIGEST_HEX_LEN]
    return f"{sanitized}-{digest}"


def _join_host_path(base: str, *parts: str) -> str:
    '''按主机操作系统拼接路径，同时兼容从 Linux 容器生成 Windows 主机路径。'''
    if not parts:
        return base

    if re.match(r"^[A-Za-z]:[\\/]", base) or base.startswith("\\\\") or "\\" in base:
        result = PureWindowsPath(base)
        for part in parts:
            result /= part
        return str(result)

    result = Path(base)
    for part in parts:
        result /= part
    return str(result)


def join_host_path(base: str, *parts: str) -> str:
    '''向外暴露主机路径拼接入口，供沙箱与宿主机文件映射共用。'''
    return _join_host_path(base, *parts)


class Paths:
    '''根据可选根目录计算应用数据、用户空间、线程目录及其宿主机映射。'''

    def __init__(self, base_dir: str | Path | None = None) -> None:
        '''保存显式指定的数据根目录；未指定时延迟读取环境配置。'''
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def host_base_dir(self) -> Path:
        '''返回宿主机可见的数据根目录，优先采用容器映射专用环境变量。'''
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return Path(env)
        return self.base_dir

    def _host_base_dir_str(self) -> str:
        '''以字符串形式返回宿主机数据根路径，保留跨操作系统拼接所需表示。'''
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return env
        return str(self.base_dir)

    @property
    def base_dir(self) -> Path:
        '''按显式参数、``DEER_FLOW_HOME``、本地默认目录的优先级确定数据根目录。'''
        if self._base_dir is not None:
            return self._base_dir

        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()

        return _default_local_base_dir()

    @property
    def memory_file(self) -> Path:
        '''返回兼容旧式全局记忆文件的路径。'''
        return self.base_dir / "memory.json"

    @property
    def user_md_file(self) -> Path:
        '''返回共享 ``USER.md`` 配置文件路径，供旧式用户提示加载逻辑使用。'''
        return self.base_dir / "USER.md"

    @property
    def agents_dir(self) -> Path:
        '''返回旧式共享自定义智能体目录；新数据应使用按用户隔离的目录。'''
        return self.base_dir / "agents"

    def agent_dir(self, name: str) -> Path:
        '''按智能体名称定位旧式共享智能体目录。'''
        return self.agents_dir / name.lower()

    def agent_memory_file(self, name: str) -> Path:
        '''定位旧式共享智能体记忆文件。'''
        return self.agent_dir(name) / "memory.json"

    def user_dir(self, user_id: str) -> Path:
        '''校验用户标识后返回该用户隔离目录。'''
        return self.base_dir / "users" / _validate_user_id(user_id)

    def prepare_user_dir_for_raw_id(self, raw_user_id: str) -> str:
        '''规范化原始用户标识，并在需要时将旧摘要格式目录迁移到新目录名。'''
        safe_user_id = make_safe_user_id(raw_user_id)
        sanitized = _UNSAFE_USER_ID_CHAR_RE.sub("-", raw_user_id)
        if safe_user_id == raw_user_id:
            return safe_user_id

        users_dir = self.base_dir / "users"
        target_dir = users_dir / safe_user_id
        legacy_dir = users_dir / _legacy_safe_user_id(raw_user_id, sanitized)
        try:
            if target_dir.exists() or not legacy_dir.is_dir():
                return safe_user_id
            legacy_dir.rename(target_dir)
            logger.info("Migrated legacy unsafe-id user directory to the current digest format")
        except OSError:
            logger.exception("Failed to migrate legacy unsafe-id user directory")
        return safe_user_id

    def user_memory_file(self, user_id: str) -> Path:
        '''返回用户级记忆文件路径。'''
        return self.user_dir(user_id) / "memory.json"

    def user_agents_dir(self, user_id: str) -> Path:
        '''返回该用户专属的自定义智能体集合目录。'''
        return self.user_dir(user_id) / "agents"

    def user_agent_dir(self, user_id: str, agent_name: str) -> Path:
        '''按用户和智能体名称定位隔离的智能体目录。'''
        return self.user_agents_dir(user_id) / agent_name.lower()

    def user_agent_memory_file(self, user_id: str, agent_name: str) -> Path:
        '''返回指定用户智能体的记忆文件路径。'''
        return self.user_agent_dir(user_id, agent_name) / "memory.json"

    def user_skills_dir(self, user_id: str) -> Path:
        '''返回该用户安装的技能目录。'''
        return self.user_dir(user_id) / "skills"

    def user_custom_skills_dir(self, user_id: str) -> Path:
        '''返回用户自定义技能子目录，与项目自带技能分开存放。'''
        return self.user_skills_dir(user_id) / "custom"

    def thread_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        '''按用户隔离策略返回线程目录；未传用户时兼容共享线程布局。'''
        if user_id is not None:
            return self.user_dir(user_id) / "threads" / _validate_thread_id(thread_id)
        return self.base_dir / "threads" / _validate_thread_id(thread_id)

    def sandbox_work_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        '''返回线程沙箱工作区路径，工具在此读写工作文件。'''
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "workspace"

    def sandbox_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        '''返回线程上传文件目录。'''
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "uploads"

    def sandbox_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        '''返回线程生成产物目录，供网关下载接口读取。'''
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "outputs"

    def acp_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        '''返回外部 ACP 智能体的独立工作目录，避免与普通沙箱文件混放。'''
        return self.thread_dir(thread_id, user_id=user_id) / "acp-workspace"

    def sandbox_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        '''返回线程下上传、工作区和产物共同使用的虚拟数据根目录。'''
        return self.thread_dir(thread_id, user_id=user_id) / "user-data"

    def host_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        '''生成宿主机可见的线程目录，用于容器内外文件路径互相映射。'''
        if user_id is not None:
            return _join_host_path(self._host_base_dir_str(), "users", _validate_user_id(user_id), "threads", _validate_thread_id(thread_id))
        return _join_host_path(self._host_base_dir_str(), "threads", _validate_thread_id(thread_id))

    def host_sandbox_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        '''生成宿主机侧线程用户数据根目录。'''
        return _join_host_path(self.host_thread_dir(thread_id, user_id=user_id), "user-data")

    def host_sandbox_work_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        '''生成宿主机侧沙箱工作区路径。'''
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "workspace")

    def host_sandbox_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        '''生成宿主机侧上传文件路径。'''
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "uploads")

    def host_sandbox_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        '''生成宿主机侧运行产物路径。'''
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "outputs")

    def host_acp_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        '''生成宿主机侧外部智能体工作区路径。'''
        return _join_host_path(self.host_thread_dir(thread_id, user_id=user_id), "acp-workspace")

    def ensure_thread_dirs(self, thread_id: str, *, user_id: str | None = None) -> None:
        '''预先创建线程运行所需的各个目录，并设置沙箱可写权限。'''
        for d in [
            self.sandbox_work_dir(thread_id, user_id=user_id),
            self.sandbox_uploads_dir(thread_id, user_id=user_id),
            self.sandbox_outputs_dir(thread_id, user_id=user_id),
            self.acp_workspace_dir(thread_id, user_id=user_id),
        ]:
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o777)

    def delete_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> None:
        '''删除指定线程的全部本地数据；调用方必须先完成所有权校验。'''
        thread_dir = self.thread_dir(thread_id, user_id=user_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)

    def resolve_virtual_path(self, thread_id: str, virtual_path: str, *, user_id: str | None = None) -> Path:
        '''将沙箱虚拟路径映射到线程数据目录，并拒绝越出该目录的路径。'''
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped != prefix and not stripped.startswith(prefix + "/"):
            raise ValueError(f"Path must start with /{prefix}")

        relative = stripped[len(prefix) :].lstrip("/")
        base = self.sandbox_user_data_dir(thread_id, user_id=user_id).resolve()
        actual = (base / relative).resolve()

        try:
            actual.relative_to(base)
        except ValueError:
            raise ValueError("Access denied: path traversal detected")

        return actual

_paths: Paths | None = None


def get_paths() -> Paths:
    '''返回进程级路径服务；首次调用时创建并缓存默认实例。'''
    global _paths
    if _paths is None:
        _paths = Paths()
    return _paths


def resolve_path(path: str) -> Path:
    '''把相对路径解释为 DeerFlow 数据根目录下的路径，并返回绝对路径。'''
    p = Path(path)
    if not p.is_absolute():
        p = get_paths().base_dir / path
    return p.resolve()
