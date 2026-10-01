'''实现沙箱工具的路径隔离、访问校验、输出脱敏与文件操作。'''

import asyncio
import json
import logging
import os
import posixpath
import re
import shlex
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from langchain.tools import tool

from deerflow.agents.thread_state import ThreadDataState
from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.runtime.secret_context import read_active_secrets
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox.exceptions import (
    SandboxError,
    SandboxNotFoundError,
    SandboxRuntimeError,
)
from deerflow.sandbox.file_operation_lock import get_file_operation_lock
from deerflow.sandbox.path_patterns import build_output_mask_pattern
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import get_sandbox_provider
from deerflow.sandbox.search import GrepMatch
from deerflow.sandbox.security import LOCAL_HOST_BASH_DISABLED_MESSAGE, is_host_bash_allowed
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![:\w])(?<!:/)/(?:[^\s\"'`;&|<>()]+)")
_IDENTIFIER_BRACE_BLOCK_PATTERN = re.compile(r"\{([^{}]*)\}")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FILE_URL_PATTERN = re.compile(r"\bfile://\S+", re.IGNORECASE)
_URL_WITH_SCHEME_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_URL_IN_COMMAND_PATTERN = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'`;&|<>()]+", re.IGNORECASE)
_DOTDOT_PATH_SEGMENT_PATTERN = re.compile(r"(?:^|[/\\=])\.\.(?:$|[/\\])")
_LOCAL_BASH_SYSTEM_PATH_PREFIXES = (
    "/bin/",
    "/usr/bin/",
    "/usr/sbin/",
    "/sbin/",
    "/opt/homebrew/bin/",
    "/dev/",
)

_DEFAULT_SKILLS_CONTAINER_PATH = DEFAULT_SKILLS_CONTAINER_PATH
_ACP_WORKSPACE_VIRTUAL_PATH = "/mnt/acp-workspace"
_DEFAULT_GLOB_MAX_RESULTS = 200
_MAX_GLOB_MAX_RESULTS = 1000
_DEFAULT_GREP_MAX_RESULTS = 100
_MAX_GREP_MAX_RESULTS = 500
_DEFAULT_WRITE_FILE_ERROR_MAX_CHARS = 2000

_WRITE_FILE_CONTENT_MAX_BYTES = 80 * 1024
_WRITE_FILE_MAX_BYTES_ENV = "DEERFLOW_WRITE_FILE_MAX_BYTES"
_LOCAL_BASH_CWD_COMMANDS = {"cd", "pushd"}
_LOCAL_BASH_COMMAND_WRAPPERS = {"command", "builtin"}
_LOCAL_BASH_COMMAND_PREFIX_KEYWORDS = {"!", "{", "case", "do", "elif", "else", "for", "if", "select", "then", "time", "until", "while"}
_LOCAL_BASH_COMMAND_END_KEYWORDS = {"}", "done", "esac", "fi"}
_LOCAL_BASH_ROOT_PATH_COMMANDS = {
    "awk",
    "cat",
    "cp",
    "du",
    "find",
    "grep",
    "head",
    "less",
    "ln",
    "ls",
    "more",
    "mv",
    "rm",
    "sed",
    "tail",
    "tar",
}
_SHELL_COMMAND_SEPARATORS = {";", "&&", "||", "|", "|&", "&", "(", ")"}
_SHELL_REDIRECTION_OPERATORS = {
    "<",
    ">",
    "<<",
    ">>",
    "<<<",
    "<>",
    ">&",
    "<&",
    "&>",
    "&>>",
    ">|",
}


def _get_skills_container_path() -> str:
    '''从配置获取技能容器路径，失败时使用默认值；仅缓存成功的读取结果。'''
    cached = getattr(_get_skills_container_path, "_cached", None)
    if cached is not None:
        return cached
    try:
        from deerflow.config import get_app_config

        value = get_app_config().skills.container_path
        _get_skills_container_path._cached = value  # type: ignore[attr-defined]
        return value
    except Exception:
        return _DEFAULT_SKILLS_CONTAINER_PATH


def _get_skills_host_path() -> str | None:
    '''从配置获取技能宿主路径；路径不存在或读取失败时返回空值且不缓存失败。'''
    cached = getattr(_get_skills_host_path, "_cached", None)
    if cached is not None:
        return cached
    try:
        from deerflow.config import get_app_config

        config = get_app_config()
        skills_path = config.skills.get_skills_path()
        if skills_path.exists():
            value = str(skills_path)
            _get_skills_host_path._cached = value  # type: ignore[attr-defined]
            return value
    except Exception:
        pass
    return None


def _is_skills_path(path: str) -> bool:
    '''判断路径是否位于技能容器路径下。'''
    skills_prefix = _get_skills_container_path()
    return path == skills_prefix or path.startswith(f"{skills_prefix}/")


def _extract_skill_name_from_skills_path(path: str) -> str | None:
    '''从虚拟技能路径提取技能名称；路径不符合技能目录结构时返回空值。'''
    skills_prefix = _get_skills_container_path()
    if not _is_skills_path(path):
        return None
    relative = path[len(skills_prefix) :].lstrip("/")
    if not relative:
        return None
    parts = [part for part in relative.split("/") if part]
    if len(parts) >= 2 and parts[0] in ("public", "custom", "legacy"):
        return parts[1]
    if len(parts) == 1 and parts[0] in ("public", "custom", "legacy"):
        return None
    if len(parts) >= 1:
        return parts[0]
    return None


def _is_disabled_skill_path(path: str, *, user_id: str | None = None) -> bool:
    '''判断路径是否属于已禁用技能。

    公共技能状态来自全局配置；自定义和旧版技能状态来自用户级状态文件。状态无法确定时
    以拒绝访问处理，避免向调用方暴露已禁用的技能文件。
    '''
    skill_name = _extract_skill_name_from_skills_path(path)
    if skill_name is None:
        return False
    try:
        from deerflow.runtime.user_context import get_effective_user_id
        from deerflow.skills.storage import get_or_new_user_skill_storage

        skills_prefix = _get_skills_container_path()
        relative = path[len(skills_prefix) :].lstrip("/")
        if relative.startswith("public/"):
            category = "public"
        elif relative.startswith("custom/"):
            category = "custom"
        elif relative.startswith("legacy/"):
            category = "legacy"
        else:
            effective_uid = user_id or get_effective_user_id()
            storage = get_or_new_user_skill_storage(effective_uid)
            all_skills = storage.load_skills(enabled_only=False)
            matching = next((s for s in all_skills if s.name == skill_name), None)
            if matching is None:
                return False
            category = matching.category.value

        if category == "public":
            from deerflow.config.extensions_config import ExtensionsConfig

            ext_config = ExtensionsConfig.from_file()
            return not ext_config.is_skill_enabled(skill_name, category)
        else:
            effective_uid = user_id or get_effective_user_id()
            storage = get_or_new_user_skill_storage(effective_uid)
            return not storage.get_skill_enabled_state(skill_name)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("Failed to determine enabled state, denying access: %s", exc)
        return True


def _drop_disabled_skill_paths(paths: list[str], *, user_id: str | None = None) -> list[str]:
    '''过滤属于已禁用技能的结果路径，并按技能缓存单次调用中的状态判定。'''
    skills_prefix = _get_skills_container_path()
    verdicts: dict[tuple[str, str], bool] = {}
    kept: list[str] = []
    for path in paths:
        skill_name = _extract_skill_name_from_skills_path(path)
        if skill_name is None:
            kept.append(path)
            continue
        category = path[len(skills_prefix) :].lstrip("/").split("/")[0]
        key = (category, skill_name)
        if key not in verdicts:
            verdicts[key] = _is_disabled_skill_path(path, user_id=user_id)
        if not verdicts[key]:
            kept.append(path)
    return kept


def _resolve_skills_path(path: str) -> str:
    '''将虚拟技能路径解析为宿主路径。

    本地沙箱中的技能路径应由获取沙箱时绑定用户的路径映射解析；本函数只用于输出脱敏和
    非沙箱调用。技能目录未配置或不存在时抛出文件未找到异常。
    '''
    skills_container = _get_skills_container_path()
    skills_host = _get_skills_host_path()
    if skills_host is None:
        raise FileNotFoundError(f"Skills directory not available for path: {path}")

    if path == skills_container:
        return skills_host

    relative = path[len(skills_container) :].lstrip("/")

    if relative == "custom" or relative.startswith("custom/"):
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import get_effective_user_id

        user_id = get_effective_user_id()
        paths = get_paths()
        user_custom_dir = paths.user_custom_skills_dir(user_id)
        custom_relative = relative[len("custom") :].lstrip("/")
        if custom_relative:
            return str(user_custom_dir / custom_relative)
        return str(user_custom_dir)

    return _join_path_preserving_style(skills_host, relative)


def _is_acp_workspace_path(path: str) -> bool:
    '''判断路径是否位于 ACP 工作区虚拟路径下。'''
    return path == _ACP_WORKSPACE_VIRTUAL_PATH or path.startswith(f"{_ACP_WORKSPACE_VIRTUAL_PATH}/")


def _get_custom_mounts():
    '''读取沙箱配置中的现有自定义挂载；仅缓存成功读取的结果。'''
    cached = getattr(_get_custom_mounts, "_cached", None)
    if cached is not None:
        return cached
    try:
        from pathlib import Path

        from deerflow.config import get_app_config

        config = get_app_config()
        mounts = []
        if config.sandbox and config.sandbox.mounts:
            mounts = [m for m in config.sandbox.mounts if Path(m.host_path).exists()]
        _get_custom_mounts._cached = mounts  # type: ignore[attr-defined]
        return mounts
    except Exception:
        return []


def _is_custom_mount_path(path: str) -> bool:
    '''判断路径是否位于某个自定义挂载的容器路径下。'''
    for mount in _get_custom_mounts():
        if path == mount.container_path or path.startswith(f"{mount.container_path}/"):
            return True
    return False


def _get_custom_mount_for_path(path: str):
    '''返回与路径匹配且前缀最长的自定义挂载配置。'''
    best = None
    for mount in _get_custom_mounts():
        if path == mount.container_path or path.startswith(f"{mount.container_path}/"):
            if best is None or len(mount.container_path) > len(best.container_path):
                best = mount
    return best


def _extract_thread_id_from_thread_data(thread_data: "ThreadDataState | None") -> str | None:
    '''通过工作区路径的目录结构从线程数据中提取线程标识。'''
    if thread_data is None:
        return None
    workspace_path = thread_data.get("workspace_path")
    if not workspace_path:
        return None
    try:
        return Path(workspace_path).parent.parent.name
    except Exception:
        return None


def _get_acp_workspace_host_path(thread_id: str | None = None) -> str | None:
    '''获取 ACP 工作区的宿主路径。

    指定线程时使用该线程的工作区且不缓存；未指定线程时回退到全局工作区，并仅缓存成功
    解析的结果。目录不存在时返回空值。
    '''
    if thread_id is not None:
        try:
            from deerflow.config.paths import get_paths
            from deerflow.runtime.user_context import get_effective_user_id

            host_path = get_paths().acp_workspace_dir(thread_id, user_id=get_effective_user_id())
            if host_path.exists():
                return str(host_path)
        except Exception:
            pass
        return None

    cached = getattr(_get_acp_workspace_host_path, "_cached", None)
    if cached is not None:
        return cached
    try:
        from deerflow.config.paths import get_paths

        host_path = get_paths().base_dir / "acp-workspace"
        if host_path.exists():
            value = str(host_path)
            _get_acp_workspace_host_path._cached = value  # type: ignore[attr-defined]
            return value
    except Exception:
        pass
    return None


def _resolve_acp_workspace_path(path: str, thread_id: str | None = None) -> str:
    '''将虚拟 ACP 工作区路径解析为宿主路径，并拒绝路径遍历。

    指定线程时解析该线程的工作区；否则使用全局工作区。工作区不存在时抛出文件未找到
    异常，路径越界时抛出权限异常。
    '''
    _reject_path_traversal(path)

    host_path = _get_acp_workspace_host_path(thread_id)
    if host_path is None:
        raise FileNotFoundError(f"ACP workspace directory not available for path: {path}")

    if path == _ACP_WORKSPACE_VIRTUAL_PATH:
        return host_path

    relative = path[len(_ACP_WORKSPACE_VIRTUAL_PATH) :].lstrip("/")
    resolved = _join_path_preserving_style(host_path, relative)

    if "/" in host_path and "\\" not in host_path:
        base_path = posixpath.normpath(host_path)
        candidate_path = posixpath.normpath(resolved)
        try:
            if posixpath.commonpath([base_path, candidate_path]) != base_path:
                raise PermissionError("Access denied: path traversal detected")
        except ValueError:
            raise PermissionError("Access denied: path traversal detected") from None
        return resolved

    resolved_path = Path(resolved).resolve()
    try:
        resolved_path.relative_to(Path(host_path).resolve())
    except ValueError:
        raise PermissionError("Access denied: path traversal detected")

    return str(resolved_path)


def _get_mcp_allowed_paths() -> list[str]:
    '''从 MCP 文件系统服务器配置中提取允许访问的路径列表。'''
    allowed_paths = []
    try:
        from deerflow.config.extensions_config import get_extensions_config

        extensions_config = get_extensions_config()

        for _, server in extensions_config.mcp_servers.items():
            if not server.enabled:
                continue

            args = server.args or []
            has_filesystem = any("server-filesystem" in arg for arg in args)
            if not has_filesystem:
                continue
            for arg in args:
                if not arg.startswith("-") and arg.startswith("/"):
                    allowed_paths.append(arg.rstrip("/") + "/")

    except Exception:
        pass

    return allowed_paths


def _get_tool_config_int(name: str, key: str, default: int) -> int:
    '''读取工具配置中的整数值；不可用时返回默认值。'''
    try:
        tool_config = get_app_config().get_tool_config(name)
        if tool_config is not None and key in tool_config.model_extra:
            value = tool_config.model_extra.get(key)
            if isinstance(value, int):
                return value
    except Exception:
        pass
    return default


def _clamp_max_results(value: int, *, default: int, upper_bound: int) -> int:
    '''将结果数量限制在有效默认值和最大上限之间。'''
    if value <= 0:
        return default
    return min(value, upper_bound)


def _resolve_max_results(name: str, requested: int, *, default: int, upper_bound: int) -> int:
    '''综合调用方请求和工具配置，得出允许的最大结果数。'''
    requested_max_results = _clamp_max_results(requested, default=default, upper_bound=upper_bound)
    configured_max_results = _clamp_max_results(
        _get_tool_config_int(name, "max_results", default),
        default=default,
        upper_bound=upper_bound,
    )
    return min(requested_max_results, configured_max_results)


def _resolve_local_read_path(path: str, thread_data: ThreadDataState) -> str:
    '''校验本地只读路径，并解析用户数据路径或保留映射路径。'''
    validate_local_tool_path(path, thread_data, read_only=True)
    if _is_skills_path(path) or _is_acp_workspace_path(path):
        return path
    return _resolve_and_validate_user_data_path(path, thread_data)


def _format_glob_results(root_path: str, matches: list[str], truncated: bool) -> str:
    '''将通配搜索结果格式化为面向工具调用者的文本。'''
    if not matches:
        return f"No files matched under {root_path}"

    lines = [f"Found {len(matches)} paths under {root_path}"]
    if truncated:
        lines[0] += f" (showing first {len(matches)})"
    lines.extend(f"{index}. {path}" for index, path in enumerate(matches, start=1))
    if truncated:
        lines.append("Results truncated. Narrow the path or pattern to see fewer matches.")
    return "\n".join(lines)


def _format_grep_results(root_path: str, matches: list[GrepMatch], truncated: bool) -> str:
    '''将文本搜索结果格式化为面向工具调用者的文本。'''
    if not matches:
        return f"No matches found under {root_path}"

    lines = [f"Found {len(matches)} matches under {root_path}"]
    if truncated:
        lines[0] += f" (showing first {len(matches)})"
    lines.extend(f"{match.path}:{match.line_number}: {match.line}" for match in matches)
    if truncated:
        lines.append("Results truncated. Narrow the path or add a glob filter.")
    return "\n".join(lines)


def _path_variants(path: str) -> set[str]:
    '''返回同一路径的原始、正斜杠和反斜杠表示。'''
    return {path, path.replace("\\", "/"), path.replace("/", "\\")}


def _path_separator_for_style(path: str) -> str:
    '''根据路径现有风格选择拼接时使用的分隔符。'''
    return "\\" if "\\" in path and "/" not in path else "/"


def _join_path_preserving_style(base: str, relative: str) -> str:
    '''拼接基础路径和相对路径，同时保留基础路径的分隔符风格。'''
    if not relative:
        return base
    separator = _path_separator_for_style(base)
    normalized_relative = relative.replace("\\" if separator == "/" else "/", separator).lstrip("/\\")
    stripped_base = base.rstrip("/\\")
    return f"{stripped_base}{separator}{normalized_relative}"


def _sanitize_error(error: Exception, runtime: Runtime | None = None) -> str:
    '''清理错误消息，避免在本地沙箱模式中泄露宿主文件系统路径。'''
    msg = f"{type(error).__name__}: {error}"
    if runtime is not None and is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        msg = mask_local_paths_in_output(msg, thread_data)
    return msg


def _truncate_write_file_error_detail(detail: str, max_chars: int) -> str:
    '''从中间截断写文件错误详情，并保留首尾内容。'''
    if max_chars == 0:
        return detail
    if len(detail) <= max_chars:
        return detail
    total = len(detail)
    marker_max_len = len(f"\n... [write_file error truncated: {total} chars skipped] ...\n")
    kept = max(0, max_chars - marker_max_len)
    if kept == 0:
        return detail[:max_chars]
    head_len = kept // 2
    tail_len = kept - head_len
    skipped = total - kept
    marker = f"\n... [write_file error truncated: {skipped} chars skipped] ...\n"
    return f"{detail[:head_len]}{marker}{detail[-tail_len:] if tail_len > 0 else ''}"


def _format_write_file_error(
    requested_path: str,
    error: Exception,
    runtime: Runtime | None = None,
    *,
    max_chars: int = _DEFAULT_WRITE_FILE_ERROR_MAX_CHARS,
) -> str:
    '''返回长度受限且已脱敏的写文件失败错误文本。'''
    header = f"Error: Failed to write file '{requested_path}'"
    detail = _sanitize_error(error, runtime)
    if max_chars == 0:
        return f"{header}: {detail}"
    detail_budget = max_chars - len(header) - 2
    if detail_budget <= 0:
        return _truncate_write_file_error_detail(f"{header}: {detail}", max_chars)
    return f"{header}: {_truncate_write_file_error_detail(detail, detail_budget)}"


def replace_virtual_path(path: str, thread_data: ThreadDataState | None) -> str:
    '''将 ``/mnt/user-data`` 下的虚拟路径替换为线程数据中的实际路径。'''
    if thread_data is None:
        return path

    mappings = _thread_virtual_to_actual_mappings(thread_data)
    if not mappings:
        return path

    for virtual_base, actual_base in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
        if path == virtual_base:
            return actual_base
        if path.startswith(f"{virtual_base}/"):
            rest = path[len(virtual_base) :].lstrip("/")
            result = _join_path_preserving_style(actual_base, rest)
            if path.endswith("/") and not result.endswith(("/", "\\")):
                result += _path_separator_for_style(actual_base)
            return result

    return path


def _thread_virtual_to_actual_mappings(thread_data: ThreadDataState) -> dict[str, str]:
    '''为线程建立从虚拟路径到实际路径的映射。'''
    mappings: dict[str, str] = {}

    workspace = thread_data.get("workspace_path")
    uploads = thread_data.get("uploads_path")
    outputs = thread_data.get("outputs_path")

    if workspace:
        mappings[f"{VIRTUAL_PATH_PREFIX}/workspace"] = workspace
    if uploads:
        mappings[f"{VIRTUAL_PATH_PREFIX}/uploads"] = uploads
    if outputs:
        mappings[f"{VIRTUAL_PATH_PREFIX}/outputs"] = outputs

    actual_dirs = [Path(p) for p in (workspace, uploads, outputs) if p]
    if actual_dirs:
        common_parent = str(Path(actual_dirs[0]).parent)
        if all(str(path.parent) == common_parent for path in actual_dirs):
            mappings[VIRTUAL_PATH_PREFIX] = common_parent

    return mappings


def _thread_actual_to_virtual_mappings(thread_data: ThreadDataState) -> dict[str, str]:
    '''为输出脱敏建立从实际路径到虚拟路径的映射。'''
    return {actual: virtual for virtual, actual in _thread_virtual_to_actual_mappings(thread_data).items()}


@lru_cache(maxsize=512)
def _compiled_mask_patterns(sources: tuple[tuple[str, str], ...]) -> tuple[tuple[re.Pattern[str], str, str], ...]:
    '''按源路径集合编译并缓存宿主路径到虚拟路径的脱敏模式。'''
    compiled: list[tuple[re.Pattern[str], str, str]] = []
    for host_base, virtual_base in sources:
        seen: set[str] = set()
        for root in (str(Path(host_base)), str(Path(host_base).resolve())):
            for variant in sorted(_path_variants(root)):
                if variant in seen:
                    continue
                seen.add(variant)
                compiled.append((build_output_mask_pattern(variant, separator_agnostic=True), variant, virtual_base))
    return tuple(compiled)


def mask_local_paths_in_output(output: str, thread_data: ThreadDataState | None) -> str:
    '''使用虚拟路径遮蔽本地沙箱输出中的宿主绝对路径。'''
    sources: list[tuple[str, str]] = []

    skills_host = _get_skills_host_path()
    if skills_host:
        sources.append((skills_host, _get_skills_container_path()))

    try:
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import get_effective_user_id

        user_id = get_effective_user_id()
        user_custom_dir = get_paths().user_custom_skills_dir(user_id)
        if user_custom_dir.exists():
            skills_container = _get_skills_container_path()
            sources.append((str(user_custom_dir), f"{skills_container}/custom"))
    except Exception:
        pass

    acp_host = _get_acp_workspace_host_path(_extract_thread_id_from_thread_data(thread_data))
    if acp_host:
        sources.append((acp_host, _ACP_WORKSPACE_VIRTUAL_PATH))

    if thread_data is not None:
        mappings = _thread_actual_to_virtual_mappings(thread_data)
        for actual_base, virtual_base in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
            sources.append((actual_base, virtual_base))

    if not sources:
        return output

    result = output
    for pattern, base, virtual in _compiled_mask_patterns(tuple(sources)):

        def replace_match(match: re.Match, _base: str = base, _virtual: str = virtual) -> str:
            '''将匹配到的宿主路径替换为对应虚拟路径。'''
            matched_path = match.group(0)
            if matched_path == _base:
                return _virtual
            relative = matched_path[len(_base) :].lstrip("/\\")
            return f"{_virtual}/{relative}" if relative else _virtual

        result = pattern.sub(replace_match, result)

    return result


def _reject_path_traversal(path: str) -> None:
    '''拒绝包含上级目录片段的路径，防止目录遍历。'''
    normalised = path.replace("\\", "/")
    for segment in normalised.split("/"):
        if segment == "..":
            raise PermissionError("Access denied: path traversal detected")


def validate_local_tool_path(path: str, thread_data: ThreadDataState | None, *, read_only: bool = False) -> None:
    '''验证虚拟路径是否允许被本地沙箱访问。

    这是安全门，仅校验访问权限而不负责解析宿主路径。用户数据可读写；技能和 ACP
    工作区只允许只读访问；自定义挂载遵循自身只读设置。线程数据缺失或路径越界时抛出异常。
    '''
    if thread_data is None:
        raise SandboxRuntimeError("Thread data not available for local sandbox")

    _reject_path_traversal(path)

    if _is_skills_path(path):
        if not read_only:
            raise PermissionError(f"Write access to skills path is not allowed: {path}")
        return

    if _is_acp_workspace_path(path):
        if not read_only:
            raise PermissionError(f"Write access to ACP workspace is not allowed: {path}")
        return

    if path.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
        return

    if _is_custom_mount_path(path):
        mount = _get_custom_mount_for_path(path)
        if mount and mount.read_only and not read_only:
            raise PermissionError(f"Write access to read-only mount is not allowed: {path}")
        return

    raise PermissionError(f"Only paths under {VIRTUAL_PATH_PREFIX}/, {_get_skills_container_path()}/, {_ACP_WORKSPACE_VIRTUAL_PATH}/, or configured mount paths are allowed")


def _validate_resolved_user_data_path(resolved: Path, thread_data: ThreadDataState) -> None:
    '''验证解析后的宿主路径仍处于该线程允许的工作区、上传或输出目录内。'''
    allowed_roots = [
        Path(p).resolve()
        for p in (
            thread_data.get("workspace_path"),
            thread_data.get("uploads_path"),
            thread_data.get("outputs_path"),
        )
        if p is not None
    ]

    if not allowed_roots:
        raise SandboxRuntimeError("No allowed local sandbox directories configured")

    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return
        except ValueError:
            continue

    raise PermissionError("Access denied: path traversal detected")


def _resolve_and_validate_user_data_path(path: str, thread_data: ThreadDataState) -> str:
    '''解析用户数据虚拟路径，并验证结果未越出线程允许范围。'''
    resolved_str = replace_virtual_path(path, thread_data)
    resolved = Path(resolved_str).resolve()
    _validate_resolved_user_data_path(resolved, thread_data)
    return str(resolved)


def _is_non_file_url_token(token: str) -> bool:
    '''判断令牌是否为不应当作文件路径处理的非文件 URL。'''
    values = [token]
    if "=" in token:
        values.append(token.split("=", 1)[1])

    for value in values:
        match = _URL_WITH_SCHEME_PATTERN.match(value)
        if match and not value.lower().startswith("file://"):
            return True
    return False


def _non_file_url_spans(command: str) -> list[tuple[int, int]]:
    '''返回命令中非文件 URL 所占的文本区间。'''
    spans = []
    for match in _URL_IN_COMMAND_PATTERN.finditer(command):
        if not match.group().lower().startswith("file://"):
            spans.append(match.span())
    return spans


def _is_in_spans(position: int, spans: list[tuple[int, int]]) -> bool:
    '''判断位置是否落在任一给定文本区间内。'''
    return any(start <= position < end for start, end in spans)


def _has_dotdot_path_segment(token: str) -> bool:
    '''判断非 URL 令牌是否含有上级目录路径片段。'''
    if _is_non_file_url_token(token):
        return False
    return bool(_DOTDOT_PATH_SEGMENT_PATTERN.search(token))


def _split_shell_tokens(command: str) -> list[str]:
    '''尽力将命令解释器命令拆分为令牌；引号错误时回退为简单拆分。'''
    try:
        normalized = command.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ; ")
        lexer = shlex.shlex(normalized, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return command.split()


def _is_shell_command_separator(token: str) -> bool:
    '''判断令牌是否为命令解释器命令分隔符。'''
    return token in _SHELL_COMMAND_SEPARATORS


def _is_shell_redirection_operator(token: str) -> bool:
    '''判断令牌是否为命令解释器重定向运算符。'''
    return token in _SHELL_REDIRECTION_OPERATORS


def _is_shell_assignment(token: str) -> bool:
    '''判断令牌是否为合法的命令解释器环境变量赋值。'''
    name, separator, _ = token.partition("=")
    if not separator or not name:
        return False
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def _is_allowed_local_bash_absolute_path(path: str, allowed_paths: list[str], *, allow_system_paths: bool) -> bool:
    '''判断绝对路径是否属于允许的挂载、用户数据或系统路径。'''
    if any(path.startswith(allowed_path) or path == allowed_path.rstrip("/") for allowed_path in allowed_paths):
        _reject_path_traversal(path)
        return True

    if path == VIRTUAL_PATH_PREFIX or path.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
        _reject_path_traversal(path)
        return True

    if _is_skills_path(path):
        _reject_path_traversal(path)
        return True

    if _is_acp_workspace_path(path):
        _reject_path_traversal(path)
        return True

    if _is_custom_mount_path(path):
        _reject_path_traversal(path)
        return True

    if allow_system_paths and any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in _LOCAL_BASH_SYSTEM_PATH_PREFIXES):
        return True

    return False


def _next_cd_target(tokens: list[str], start_index: int) -> tuple[str | None, int]:
    '''从令牌序列中读取下一个 ``cd`` 或 ``pushd`` 的目标路径。'''
    index = start_index
    while index < len(tokens):
        token = tokens[index]
        if _is_shell_command_separator(token):
            return None, index
        if _is_shell_redirection_operator(token):
            index += 2
            continue
        if token == "--":
            index += 1
            continue
        if token in {"-L", "-P", "-e", "-@"}:
            index += 1
            continue
        if token.startswith("-") and token != "-":
            index += 1
            continue
        return token, index + 1
    return None, index


def _validate_local_bash_cwd_target(command_name: str, target: str | None, allowed_paths: list[str]) -> None:
    '''校验本地命令解释器改变工作目录的目标路径是否安全。'''
    if target is None or target == "-":
        raise PermissionError(f"Unsafe working directory change in command: {command_name}. Use paths under {VIRTUAL_PATH_PREFIX}")
    if target.startswith(("$", "`")):
        raise PermissionError(f"Unsafe working directory change in command: {command_name} {target}. Use paths under {VIRTUAL_PATH_PREFIX}")
    if target.startswith("~"):
        raise PermissionError(f"Unsafe working directory change in command: {command_name} {target}. Use paths under {VIRTUAL_PATH_PREFIX}")
    if target.startswith("/"):
        _reject_path_traversal(target)
        if not _is_allowed_local_bash_absolute_path(target, allowed_paths, allow_system_paths=False):
            raise PermissionError(f"Unsafe working directory change in command: {command_name} {target}. Use paths under {VIRTUAL_PATH_PREFIX}")


def _validate_local_bash_root_path_args(command_name: str, tokens: list[str], start_index: int) -> None:
    '''拒绝特定文件工具把根目录作为路径参数使用。'''
    if command_name not in _LOCAL_BASH_ROOT_PATH_COMMANDS:
        return

    index = start_index
    while index < len(tokens):
        token = tokens[index]
        if _is_shell_command_separator(token):
            return
        if _is_shell_redirection_operator(token):
            index += 2
            continue
        if token == "/" and not _is_non_file_url_token(token):
            raise PermissionError(f"Unsafe absolute paths in command: /. Use paths under {VIRTUAL_PATH_PREFIX}")
        index += 1


def _validate_local_bash_shell_tokens(command: str, allowed_paths: list[str]) -> None:
    '''保守地拒绝绝对路径扫描未捕获的相对路径逃逸。'''
    if re.search(r"\$\([^)]*\b(?:cd|pushd)\b", command):
        raise PermissionError(f"Unsafe working directory change in command substitution. Use paths under {VIRTUAL_PATH_PREFIX}")

    tokens = _split_shell_tokens(command)

    for token in tokens:
        if _is_shell_command_separator(token) or _is_shell_redirection_operator(token):
            continue
        if _has_dotdot_path_segment(token):
            raise PermissionError("Access denied: path traversal detected")

    at_command_start = True
    index = 0
    while index < len(tokens):
        token = tokens[index]

        if _is_shell_command_separator(token):
            at_command_start = True
            index += 1
            continue

        if _is_shell_redirection_operator(token):
            index += 1
            continue

        if at_command_start and _is_shell_assignment(token):
            index += 1
            continue

        command_name = token.rsplit("/", 1)[-1]
        if at_command_start and command_name in _LOCAL_BASH_COMMAND_PREFIX_KEYWORDS | _LOCAL_BASH_COMMAND_END_KEYWORDS:
            index += 1
            continue

        if not at_command_start:
            index += 1
            continue

        at_command_start = False
        if command_name in _LOCAL_BASH_COMMAND_WRAPPERS and index + 1 < len(tokens):
            wrapped_name = tokens[index + 1].rsplit("/", 1)[-1]
            if wrapped_name in _LOCAL_BASH_CWD_COMMANDS:
                target, next_index = _next_cd_target(tokens, index + 2)
                _validate_local_bash_cwd_target(wrapped_name, target, allowed_paths)
                index = next_index
                continue
            _validate_local_bash_root_path_args(wrapped_name, tokens, index + 2)

        if command_name not in _LOCAL_BASH_CWD_COMMANDS:
            _validate_local_bash_root_path_args(command_name, tokens, index + 1)
            index += 1
            continue

        target, next_index = _next_cd_target(tokens, index + 1)
        _validate_local_bash_cwd_target(command_name, target, allowed_paths)
        index = next_index


def resolve_and_validate_user_data_path(path: str, thread_data: ThreadDataState) -> str:
    '''公开解析并验证用户数据虚拟路径仍在允许边界内。'''
    return _resolve_and_validate_user_data_path(path, thread_data)


def _braces_are_identifier_placeholders_only(fragment: str) -> bool:
    '''仅当每个花括号块都是单一标识符占位符时返回真。

    REST 模板和格式化字符串中的标识符占位符是文本；命令解释器花括号或变量展开可能在运行时
    还原真实宿主路径，因此不能豁免。游离、空或嵌套花括号同样不被接受。
    '''
    if "${" in fragment:
        return False
    blocks = _IDENTIFIER_BRACE_BLOCK_PATTERN.findall(fragment)
    if fragment.count("{") != len(blocks) or fragment.count("}") != len(blocks):
        return False
    return all(_IDENTIFIER_PATTERN.fullmatch(inner) for inner in blocks)


def _is_non_path_literal_fragment(fragment: str) -> bool:
    '''判断类似 ``/片段`` 的命中几乎确定是文本而非路径。

    原始命令扫描也会命中字面量、格式化字符串和 REST 模板；非 ASCII 字符及单一标识符
    占位符可消除这类误报。此规则不是安全边界，真正的 ASCII 宿主路径仍会被拒绝。
    '''
    if any(ord(ch) > 127 for ch in fragment):
        return True
    if "{" in fragment or "}" in fragment:
        return _braces_are_identifier_placeholders_only(fragment)
    return False


def validate_local_bash_command_paths(command: str, thread_data: ThreadDataState | None) -> None:
    '''校验本地沙箱命令解释器命令中的绝对路径。

    此校验仅是显式允许宿主命令时的尽力防护，不构成宿主文件系统隔离。用户数据必须使用
    虚拟路径；技能、ACP 工作区和自定义挂载允许通过遍历检查；常见可执行文件和设备路径
    使用较小的白名单。
    '''
    if thread_data is None:
        raise SandboxRuntimeError("Thread data not available for local sandbox")

    file_url_match = _FILE_URL_PATTERN.search(command)
    if file_url_match:
        raise PermissionError(f"Unsafe file:// URL in command: {file_url_match.group()}. Use paths under {VIRTUAL_PATH_PREFIX}")

    unsafe_paths: list[str] = []
    allowed_paths = _get_mcp_allowed_paths()
    _validate_local_bash_shell_tokens(command, allowed_paths)
    url_spans = _non_file_url_spans(command)

    for match in _ABSOLUTE_PATH_PATTERN.finditer(command):
        if _is_in_spans(match.start(), url_spans):
            continue
        absolute_path = match.group()
        if _is_non_path_literal_fragment(absolute_path):
            continue
        if _is_allowed_local_bash_absolute_path(absolute_path, allowed_paths, allow_system_paths=True):
            continue

        unsafe_paths.append(absolute_path)

    if unsafe_paths:
        unsafe = ", ".join(sorted(dict.fromkeys(unsafe_paths)))
        raise PermissionError(f"Unsafe absolute paths in command: {unsafe}. Use paths under {VIRTUAL_PATH_PREFIX}")


def replace_virtual_paths_in_command(command: str, thread_data: ThreadDataState | None) -> str:
    '''将本地沙箱命令中的用户数据虚拟路径替换为实际线程路径。

    技能和 ACP 工作区路径由执行时的路径映射解析，以使用获取沙箱时绑定的正确用户标识；
    这里不预先解析它们。
    '''
    result = command


    if VIRTUAL_PATH_PREFIX in result and thread_data is not None:
        pattern = re.compile(rf"{re.escape(VIRTUAL_PATH_PREFIX)}(?=/|$|[^\w./-])(/[^\s\"';&|<>()]*)?")

        def replace_user_data_match(match: re.Match) -> str:
            '''将匹配到的用户数据虚拟路径替换为实际线程路径。'''
            return replace_virtual_path(match.group(0), thread_data).replace("\\", "/")

        result = pattern.sub(replace_user_data_match, result)

    return result


def _apply_cwd_prefix(command: str, thread_data: ThreadDataState | None) -> str:
    '''为命令添加工作区切换前缀，使相对路径锚定到线程工作区。'''
    if thread_data and (workspace := thread_data.get("workspace_path")):
        return f"cd {shlex.quote(workspace)} && {command}"
    return command


def get_thread_data(runtime: Runtime | None) -> ThreadDataState | None:
    '''从运行时状态中提取线程数据。'''
    if runtime is None:
        return None
    if runtime.state is None:
        return None
    return runtime.state.get("thread_data")


def is_local_sandbox(runtime: Runtime | None) -> bool:
    '''判断当前沙箱是否为通用或线程范围的本地沙箱。'''
    if runtime is None:
        return False
    if runtime.state is None:
        return False
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        return False
    sandbox_id = sandbox_state.get("sandbox_id")
    if not isinstance(sandbox_id, str):
        return False
    return sandbox_id == "local" or sandbox_id.startswith("local:")


def sandbox_from_runtime(runtime: Runtime | None = None) -> Sandbox:
    '''从工具运行时取得已初始化的沙箱实例；缺失时抛出相应异常。'''
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")
    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        raise SandboxRuntimeError("Sandbox state not initialized in runtime")
    sandbox_id = sandbox_state.get("sandbox_id")
    if sandbox_id is None:
        raise SandboxRuntimeError("Sandbox ID not found in state")
    sandbox = get_sandbox_provider().get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError(f"Sandbox with ID '{sandbox_id}' not found", sandbox_id=sandbox_id)

    if runtime.context is not None:
        runtime.context["sandbox_id"] = sandbox_id
    return sandbox


def ensure_sandbox_initialized(runtime: Runtime | None = None) -> Sandbox:
    '''确保沙箱已初始化；首次调用时按线程延迟获取并写入运行时状态。'''
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")

    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")

    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is not None:
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is not None:
            sandbox = get_sandbox_provider().get(sandbox_id)
            if sandbox is not None:
                if runtime.context is not None:
                    runtime.context["sandbox_id"] = sandbox_id
                return sandbox

    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id is None:
        thread_id = runtime.config.get("configurable", {}).get("thread_id") if runtime.config else None
    if thread_id is None:
        raise SandboxRuntimeError("Thread ID not available in runtime context")

    provider = get_sandbox_provider()
    sandbox_id = provider.acquire(thread_id, user_id=resolve_runtime_user_id(runtime))

    runtime.state["sandbox"] = {"sandbox_id": sandbox_id}

    sandbox = provider.get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError("Sandbox not found after acquisition", sandbox_id=sandbox_id)

    if runtime.context is not None:
        runtime.context["sandbox_id"] = sandbox_id
    return sandbox


async def ensure_sandbox_initialized_async(runtime: Runtime | None = None) -> Sandbox:
    '''异步运行时的延迟沙箱初始化入口，使用提供者异步获取钩子。'''
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")

    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")

    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is not None:
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is not None:
            sandbox = get_sandbox_provider().get(sandbox_id)
            if sandbox is not None:
                if runtime.context is not None:
                    runtime.context["sandbox_id"] = sandbox_id
                return sandbox

    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id is None:
        thread_id = runtime.config.get("configurable", {}).get("thread_id") if runtime.config else None
    if thread_id is None:
        raise SandboxRuntimeError("Thread ID not available in runtime context")

    provider = get_sandbox_provider()
    sandbox_id = await provider.acquire_async(thread_id, user_id=resolve_runtime_user_id(runtime))

    runtime.state["sandbox"] = {"sandbox_id": sandbox_id}

    sandbox = provider.get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError("Sandbox not found after acquisition", sandbox_id=sandbox_id)

    if runtime.context is not None:
        runtime.context["sandbox_id"] = sandbox_id
    return sandbox


async def _run_sync_tool_after_async_sandbox_init(
    func: Callable[..., str] | None,
    runtime: Runtime,
    *args: object,
) -> str:
    '''通过异步提供者延迟初始化沙箱，再在线程中运行同步工具主体。'''
    try:
        await ensure_sandbox_initialized_async(runtime)
    except SandboxError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Unexpected error initializing sandbox: {_sanitize_error(e, runtime)}"

    if func is None:
        return "Error: Tool implementation not available"

    return await asyncio.to_thread(func, runtime, *args)


def ensure_thread_directories_exist(runtime: Runtime | None) -> None:
    '''确保线程的工作区、上传和输出目录存在；仅本地沙箱创建实体目录。'''
    if runtime is None:
        return

    if not is_local_sandbox(runtime):
        return

    thread_data = get_thread_data(runtime)
    if thread_data is None:
        return

    if runtime.state.get("thread_directories_created"):
        return

    import os

    for key in ["workspace_path", "uploads_path", "outputs_path"]:
        path = thread_data.get(key)
        if path:
            os.makedirs(path, exist_ok=True)

    runtime.state["thread_directories_created"] = True


_SECRET_REDACTION = "[redacted]"

_MIN_MASK_LENGTH = 8


def mask_secret_values(output: str, injected_env: dict[str, str] | None) -> str:
    '''在命令输出重新进入上下文前遮蔽注入的密钥值。

    按长度从长到短替换非空密钥，避免较短值先替换而泄露较长值的一部分；过短值不遮蔽，
    以免破坏无关输出。
    '''
    if not injected_env or not output:
        return output
    for value in sorted((v for v in injected_env.values() if v and len(v) >= _MIN_MASK_LENGTH), key=len, reverse=True):
        output = output.replace(value, _SECRET_REDACTION)
    return output


def _truncate_bash_output(output: str, max_chars: int) -> str:
    '''从中间截断命令输出并等量保留首尾；零上限表示不截断。'''
    if max_chars == 0:
        return output
    if len(output) <= max_chars:
        return output
    total_len = len(output)
    marker_max_len = len(f"\n... [middle truncated: {total_len} chars skipped] ...\n")
    kept = max(0, max_chars - marker_max_len)
    if kept == 0:
        return output[:max_chars]
    head_len = kept // 2
    tail_len = kept - head_len
    skipped = total_len - kept
    marker = f"\n... [middle truncated: {skipped} chars skipped] ...\n"
    return f"{output[:head_len]}{marker}{output[-tail_len:] if tail_len > 0 else ''}"


def _truncate_read_file_output(output: str, max_chars: int) -> str:
    '''从尾部截断读文件输出并保留开头；零上限表示不截断。'''
    if max_chars == 0:
        return output
    if len(output) <= max_chars:
        return output
    total = len(output)
    marker_max_len = len(f"\n... [truncated: showing first {total} of {total} chars. Use start_line/end_line to read a specific range] ...")
    kept = max(0, max_chars - marker_max_len)
    if kept == 0:
        return output[:max_chars]
    marker = f"\n... [truncated: showing first {kept} of {total} chars. Use start_line/end_line to read a specific range] ..."
    return f"{output[:kept]}{marker}"


def _truncate_ls_output(output: str, max_chars: int) -> str:
    '''从尾部截断目录列表输出并保留开头；零上限表示不截断。'''
    if max_chars == 0:
        return output
    if len(output) <= max_chars:
        return output
    total = len(output)
    marker_max_len = len(f"\n... [truncated: showing first {total} of {total} chars. Use a more specific path to see fewer results] ...")
    kept = max(0, max_chars - marker_max_len)
    if kept == 0:
        return output[:max_chars]
    marker = f"\n... [truncated: showing first {kept} of {total} chars. Use a more specific path to see fewer results] ..."
    return f"{output[:kept]}{marker}"


CHANNEL_USER_ID_ENV = "DEERFLOW_CHANNEL_USER_ID"

_CHANNEL_USER_ID_CONTEXT_KEY = "channel_user_id"

_CHANNEL_USER_ID_MAX_LEN = 256


def _is_windows() -> bool:
    '''判断当前运行平台是否为 Windows。'''
    return os.name == "nt"


def _channel_identity_prefix(runtime: Runtime) -> str | None:
    '''构造设置或清除渠道用户标识环境变量的命令前缀。

    非即时通讯运行不修改命令；即时通讯运行每次都会显式导出有效标识，或清除无效标识，
    以免共享命令解释器会话继承此前发送者的标识。该标识不是密钥，可保留在审计可见命令中。
    '''
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict) or _CHANNEL_USER_ID_CONTEXT_KEY not in context:
        return None
    channel_user_id = context.get(_CHANNEL_USER_ID_CONTEXT_KEY)
    if isinstance(channel_user_id, str) and 0 < len(channel_user_id) <= _CHANNEL_USER_ID_MAX_LEN:
        return f"export {CHANNEL_USER_ID_ENV}={shlex.quote(channel_user_id)}; "
    return f"unset {CHANNEL_USER_ID_ENV}; "


@tool("bash", parse_docstring=True)
def bash_tool(runtime: Runtime, description: str, command: str) -> str:
    '''在沙箱当前目录运行命令，并返回执行结果。


    - Use `python` to run Python code.
    - Prefer a thread-local virtual environment in `/mnt/user-data/workspace/.venv`.
    - Use `python -m pip` (inside the virtual environment) to install Python packages.
    - To start a long-lived process such as a web server, ALWAYS run it in the background with its
      output redirected, e.g. `your-command > /mnt/user-data/workspace/server.log 2>&1 &`, then check
      the log file or poll the port. A long-lived process run in the foreground blocks the turn until
      it is killed at the command timeout.

    Args:
        description: Explain why you are running this command in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        command: The bash command to execute. Always use absolute paths for files and directories.
    '''
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        injected_env = read_active_secrets(getattr(runtime, "context", None)) or None
        identity_prefix = _channel_identity_prefix(runtime)
        if is_local_sandbox(runtime):
            if not is_host_bash_allowed():
                return f"Error: {LOCAL_HOST_BASH_DISABLED_MESSAGE}"
            ensure_thread_directories_exist(runtime)
            thread_data = get_thread_data(runtime)
            validate_local_bash_command_paths(command, thread_data)
            command = replace_virtual_paths_in_command(command, thread_data)
            command = _apply_cwd_prefix(command, thread_data)
            if identity_prefix and not _is_windows():
                command = identity_prefix + command
            try:
                from deerflow.config.app_config import get_app_config

                sandbox_cfg = get_app_config().sandbox
                max_chars = sandbox_cfg.bash_output_max_chars if sandbox_cfg else 20000
                command_timeout = sandbox_cfg.bash_command_timeout if sandbox_cfg else None
            except Exception:
                max_chars = 20000
                command_timeout = None
            output = sandbox.execute_command(command, env=injected_env, timeout=command_timeout)
            return _truncate_bash_output(
                mask_secret_values(mask_local_paths_in_output(output, thread_data), injected_env),
                max_chars,
            )
        ensure_thread_directories_exist(runtime)
        command = f"cd {VIRTUAL_PATH_PREFIX}/workspace; {command}"
        if identity_prefix:
            command = identity_prefix + command
        try:
            from deerflow.config.app_config import get_app_config

            sandbox_cfg = get_app_config().sandbox
            max_chars = sandbox_cfg.bash_output_max_chars if sandbox_cfg else 20000
        except Exception:
            max_chars = 20000
        return _truncate_bash_output(mask_secret_values(sandbox.execute_command(command, env=injected_env), injected_env), max_chars)
    except SandboxError as e:
        return f"Error: {e}"
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Unexpected error executing command: {_sanitize_error(e, runtime)}"


async def _bash_tool_async(runtime: Runtime, description: str, command: str) -> str:
    '''异步初始化沙箱后在线程中执行命令工具。'''
    return await _run_sync_tool_after_async_sandbox_init(bash_tool.func, runtime, description, command)


bash_tool.coroutine = _bash_tool_async


@tool("ls", parse_docstring=True)
def ls_tool(runtime: Runtime, description: str, path: str) -> str:
    '''以树形结构列出目录内容，最多展开两层。

    Args:
        description: Explain why you are listing this directory in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the directory to list.
    '''
    try:
        user_id = resolve_runtime_user_id(runtime)
        if _is_disabled_skill_path(path, user_id=user_id):
            skill_name = _extract_skill_name_from_skills_path(path) or "unknown"
            return f"Error: Skill '{skill_name}' is disabled. Access to its files is blocked. Enable the skill in settings before using it."
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        requested_path = path
        thread_data = None
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            validate_local_tool_path(path, thread_data, read_only=True)
            if _is_skills_path(path) or _is_acp_workspace_path(path):
                pass
            elif not _is_custom_mount_path(path):
                path = _resolve_and_validate_user_data_path(path, thread_data)
        children = sandbox.list_dir(path)
        if not children:
            return "(empty)"
        output = "\n".join(children)
        if thread_data is not None:
            output = mask_local_paths_in_output(output, thread_data)
        entries = _drop_disabled_skill_paths(output.splitlines(), user_id=user_id)
        if not entries:
            return "(empty)"
        output = "\n".join(entries)
        try:
            from deerflow.config.app_config import get_app_config

            sandbox_cfg = get_app_config().sandbox
            max_chars = sandbox_cfg.ls_output_max_chars if sandbox_cfg else 20000
        except Exception:
            max_chars = 20000
        return _truncate_ls_output(output, max_chars)
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: Directory not found: {requested_path}"
    except PermissionError:
        return f"Error: Permission denied: {requested_path}"
    except Exception as e:
        return f"Error: Unexpected error listing directory: {_sanitize_error(e, runtime)}"


async def _ls_tool_async(runtime: Runtime, description: str, path: str) -> str:
    '''异步初始化沙箱后在线程中执行目录列表工具。'''
    return await _run_sync_tool_after_async_sandbox_init(ls_tool.func, runtime, description, path)


ls_tool.coroutine = _ls_tool_async


@tool("glob", parse_docstring=True)
def glob_tool(
    runtime: Runtime,
    description: str,
    pattern: str,
    path: str,
    include_dirs: bool = False,
    max_results: int = _DEFAULT_GLOB_MAX_RESULTS,
) -> str:
    '''在指定根目录内按 glob 模式查找文件或子目录。

    Args:
        description: Explain why you are searching for these paths in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        pattern: The glob pattern to match relative to the root path, for example `**/*.py`.
        path: The **absolute** root directory to search under.
        include_dirs: Whether matching directories should also be returned. Default is False.
        max_results: Maximum number of paths to return. Default is 200.
    '''
    try:
        user_id = resolve_runtime_user_id(runtime)
        if _is_disabled_skill_path(path, user_id=user_id):
            skill_name = _extract_skill_name_from_skills_path(path) or "unknown"
            return f"Error: Skill '{skill_name}' is disabled. Access to its files is blocked. Enable the skill in settings before using it."
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        requested_path = path
        effective_max_results = _resolve_max_results(
            "glob",
            max_results,
            default=_DEFAULT_GLOB_MAX_RESULTS,
            upper_bound=_MAX_GLOB_MAX_RESULTS,
        )
        thread_data = None
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            if thread_data is None:
                raise SandboxRuntimeError("Thread data not available for local sandbox")
            path = _resolve_local_read_path(path, thread_data)
        matches, truncated = sandbox.glob(path, pattern, include_dirs=include_dirs, max_results=effective_max_results)
        if thread_data is not None:
            matches = [mask_local_paths_in_output(match, thread_data) for match in matches]
        matches = _drop_disabled_skill_paths(matches, user_id=user_id)
        return _format_glob_results(requested_path, matches, truncated)
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: Directory not found: {requested_path}"
    except NotADirectoryError:
        return f"Error: Path is not a directory: {requested_path}"
    except PermissionError:
        return f"Error: Permission denied: {requested_path}"
    except Exception as e:
        return f"Error: Unexpected error searching paths: {_sanitize_error(e, runtime)}"


async def _glob_tool_async(
    runtime: Runtime,
    description: str,
    pattern: str,
    path: str,
    include_dirs: bool = False,
    max_results: int = _DEFAULT_GLOB_MAX_RESULTS,
) -> str:
    '''异步初始化沙箱后在线程中执行通配搜索工具。'''
    return await _run_sync_tool_after_async_sandbox_init(
        glob_tool.func,
        runtime,
        description,
        pattern,
        path,
        include_dirs,
        max_results,
    )


glob_tool.coroutine = _glob_tool_async


@tool("grep", parse_docstring=True)
def grep_tool(
    runtime: Runtime,
    description: str,
    pattern: str,
    path: str,
    glob: str | None = None,
    literal: bool = False,
    case_sensitive: bool = False,
    max_results: int = _DEFAULT_GREP_MAX_RESULTS,
) -> str:
    '''在指定根目录的文本文件中查找匹配内容，并返回上下文行。

    Args:
        description: Explain why you are searching file contents in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        pattern: The string or regex pattern to search for.
        path: The **absolute** root directory to search under.
        glob: Optional glob filter for candidate files, for example `**/*.py`.
        literal: Whether to treat `pattern` as a plain string. Default is False.
        case_sensitive: Whether matching is case-sensitive. Default is False.
        max_results: Maximum number of matching lines to return. Default is 100.
    '''
    try:
        user_id = resolve_runtime_user_id(runtime)
        if _is_disabled_skill_path(path, user_id=user_id):
            skill_name = _extract_skill_name_from_skills_path(path) or "unknown"
            return f"Error: Skill '{skill_name}' is disabled. Access to its files is blocked. Enable the skill in settings before using it."
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        requested_path = path
        effective_max_results = _resolve_max_results(
            "grep",
            max_results,
            default=_DEFAULT_GREP_MAX_RESULTS,
            upper_bound=_MAX_GREP_MAX_RESULTS,
        )
        thread_data = None
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            if thread_data is None:
                raise SandboxRuntimeError("Thread data not available for local sandbox")
            path = _resolve_local_read_path(path, thread_data)
        matches, truncated = sandbox.grep(
            path,
            pattern,
            glob=glob,
            literal=literal,
            case_sensitive=case_sensitive,
            max_results=effective_max_results,
        )
        if thread_data is not None:
            matches = [
                GrepMatch(
                    path=mask_local_paths_in_output(match.path, thread_data),
                    line_number=match.line_number,
                    line=match.line,
                )
                for match in matches
            ]
        allowed = set(_drop_disabled_skill_paths([match.path for match in matches], user_id=user_id))
        matches = [match for match in matches if match.path in allowed]
        return _format_grep_results(requested_path, matches, truncated)
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: Directory not found: {requested_path}"
    except NotADirectoryError:
        return f"Error: Path is not a directory: {requested_path}"
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"
    except PermissionError:
        return f"Error: Permission denied: {requested_path}"
    except Exception as e:
        return f"Error: Unexpected error searching file contents: {_sanitize_error(e, runtime)}"


async def _grep_tool_async(
    runtime: Runtime,
    description: str,
    pattern: str,
    path: str,
    glob: str | None = None,
    literal: bool = False,
    case_sensitive: bool = False,
    max_results: int = _DEFAULT_GREP_MAX_RESULTS,
) -> str:
    '''异步初始化沙箱后在线程中执行文本搜索工具。'''
    return await _run_sync_tool_after_async_sandbox_init(
        grep_tool.func,
        runtime,
        description,
        pattern,
        path,
        glob,
        literal,
        case_sensitive,
        max_results,
    )


grep_tool.coroutine = _grep_tool_async


def read_current_file_content(runtime: Runtime | None, path: str) -> str:
    '''按读文件工具的路径解析规则读取文件当前完整内容，供读写门禁复用。'''
    sandbox = ensure_sandbox_initialized(runtime)
    ensure_thread_directories_exist(runtime)
    if is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        validate_local_tool_path(path, thread_data, read_only=True)
        if _is_skills_path(path):
            path = _resolve_skills_path(path)
        elif _is_acp_workspace_path(path):
            path = _resolve_acp_workspace_path(path, _extract_thread_id_from_thread_data(thread_data))
        elif not _is_custom_mount_path(path):
            path = _resolve_and_validate_user_data_path(path, thread_data)
    return sandbox.read_file(path)


@tool("read_file", parse_docstring=True)
def read_file_tool(
    runtime: Runtime,
    description: str,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    '''读取文本文件，供检查源码、配置、日志或其他文字资料。

    Args:
        description: Explain why you are reading this file in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to read.
        start_line: Optional starting line number (1-indexed, inclusive). Use with end_line to read a specific range.
        end_line: Optional ending line number (1-indexed, inclusive). Use with start_line to read a specific range.
    '''
    try:
        if _is_disabled_skill_path(path, user_id=resolve_runtime_user_id(runtime)):
            skill_name = _extract_skill_name_from_skills_path(path) or "unknown"
            return f"Error: Skill '{skill_name}' is disabled. Access to its files is blocked. Enable the skill in settings before using it."
        requested_path = path
        content = read_current_file_content(runtime, path)
        if not content:
            return "(empty)"
        if start_line is not None or end_line is not None:
            lines = content.splitlines()
            s = max(start_line, 1) if start_line is not None else 1
            e = end_line if end_line is not None else len(lines)
            if e < 1:
                return "(end_line must be >= 1)"
            if s > len(lines):
                return "(start_line exceeds file length)"
            if s > e:
                return "(start_line > end_line — no lines in range)"
            content = "\n".join(lines[s - 1 : e])
        try:
            from deerflow.config.app_config import get_app_config

            sandbox_cfg = get_app_config().sandbox
            max_chars = sandbox_cfg.read_file_output_max_chars if sandbox_cfg else 50000
        except Exception:
            max_chars = 50000
        return _truncate_read_file_output(content, max_chars)
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: File not found: {requested_path}"
    except PermissionError:
        return f"Error: Permission denied reading file: {requested_path}"
    except IsADirectoryError:
        return f"Error: Path is a directory, not a file: {requested_path}"
    except UnicodeDecodeError:
        return (
            f"Error: cannot read '{requested_path}' as text — it appears to be a binary file "
            "(e.g. .xlsx, .pdf, or an image). read_file only supports UTF-8 text. Use bash with a "
            "suitable library instead (pandas/openpyxl for spreadsheets), or view_image for images."
        )
    except Exception as e:
        return f"Error: Unexpected error reading file: {_sanitize_error(e, runtime)}"


async def _read_file_tool_async(
    runtime: Runtime,
    description: str,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    '''异步初始化沙箱后在线程中执行读文件工具。'''
    return await _run_sync_tool_after_async_sandbox_init(read_file_tool.func, runtime, description, path, start_line, end_line)


read_file_tool.coroutine = _read_file_tool_async


def _effective_write_file_max_bytes() -> int:
    '''返回非追加写入的当前大小上限；无效配置回退默认值，非正值关闭限制。'''
    raw = os.environ.get(_WRITE_FILE_MAX_BYTES_ENV)
    if raw is None:
        return _WRITE_FILE_CONTENT_MAX_BYTES
    try:
        return int(raw)
    except ValueError:
        return _WRITE_FILE_CONTENT_MAX_BYTES


@tool("write_file", parse_docstring=True)
def write_file_tool(
    runtime: Runtime,
    description: str,
    path: str,
    content: str,
    append: bool = False,
) -> str:
    '''将文本写入文件；默认覆盖原内容，也可选择追加到文件末尾。

    READ-BEFORE-WRITE (issue #3857): if the target file already exists (including
    append=True), you must have read its CURRENT version with read_file first.
    Any write invalidates earlier reads, so re-read between consecutive
    modifications — a ranged read of the relevant section is enough. Writes
    that fail this check are rejected with an error.

    SIZE POLICY (issue #3189):
    A single non-append write_file call must not exceed 80 KB of UTF-8 content.
    Oversized single-shot writes correlate with LLM streaming chunk-gap
    timeouts because the tool-call JSON payload — which the model must emit as
    one continuous stream — grows past the safe window. For larger documents,
    use ONE of these strategies (write_file rejects oversized payloads with an
    actionable error):

      1. INCREMENTAL EDIT (preferred for revisions): after the initial write,
         use `str_replace` to surgically update sections. This is the same
         pattern Claude Code's Write+Edit and OpenAI Codex's apply_patch use,
         and keeps each tool call's payload small.
      2. APPEND-IN-CHUNKS (for new long-form content): split the document into
         sections, each well under 80 KB. First call uses append=False to
         create the file; subsequent calls use append=True. The 80 KB cap does
         NOT apply to append=True calls.

    Operators can override the cap via env var `DEERFLOW_WRITE_FILE_MAX_BYTES`
    (0 disables the guard entirely). Raising it risks streaming timeouts.

    Args:
        description: Explain why you are writing to this file in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to write to. ALWAYS PROVIDE THIS PARAMETER SECOND.
        content: The content to write to the file. ALWAYS PROVIDE THIS PARAMETER THIRD.
        append: Whether to append content to the end of the file instead of overwriting it. Defaults to False.
    '''
    if not append:
        max_bytes = _effective_write_file_max_bytes()
        if max_bytes > 0:
            content_bytes = len(content.encode("utf-8"))
            if content_bytes > max_bytes:
                return (
                    f"Error: write_file content ({content_bytes} bytes) exceeds the "
                    f"{max_bytes}-byte single-call limit. Split the content into smaller "
                    "pieces: either (a) write the first section now, then use `str_replace` "
                    "for further edits, or (b) call write_file again with append=True "
                    "carrying the next section. See SIZE POLICY in the tool docstring "
                    "or issue #3189 for the rationale."
                )
    try:
        requested_path = path
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            validate_local_tool_path(path, thread_data)
            if not _is_custom_mount_path(path):
                path = _resolve_and_validate_user_data_path(path, thread_data)
        with get_file_operation_lock(sandbox, path):
            sandbox.write_file(path, content, append)
        return "OK"
    except SandboxError as e:
        return _format_write_file_error(requested_path, e, runtime)
    except PermissionError:
        return _truncate_write_file_error_detail(
            f"Error: Permission denied writing to file: {requested_path}",
            _DEFAULT_WRITE_FILE_ERROR_MAX_CHARS,
        )
    except IsADirectoryError:
        return _truncate_write_file_error_detail(
            f"Error: Path is a directory, not a file: {requested_path}",
            _DEFAULT_WRITE_FILE_ERROR_MAX_CHARS,
        )
    except OSError as e:
        return _format_write_file_error(requested_path, e, runtime)
    except Exception as e:
        return _format_write_file_error(requested_path, e, runtime)


async def _write_file_tool_async(
    runtime: Runtime,
    description: str,
    path: str,
    content: str,
    append: bool = False,
) -> str:
    '''异步初始化沙箱后在线程中执行写文件工具。'''
    return await _run_sync_tool_after_async_sandbox_init(write_file_tool.func, runtime, description, path, content, append)


write_file_tool.coroutine = _write_file_tool_async


@tool("str_replace", parse_docstring=True)
def str_replace_tool(
    runtime: Runtime,
    description: str,
    path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
) -> str:
    '''在文件中查找指定片段并替换为新内容。
    If `replace_all` is False (default), the substring to replace must appear **exactly once** in the file.

    READ-BEFORE-WRITE (issue #3857): you must have read the file's CURRENT
    version with read_file first; any write invalidates earlier reads.

    Args:
        description: Explain why you are replacing the substring in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to replace the substring in. ALWAYS PROVIDE THIS PARAMETER SECOND.
        old_str: The substring to replace. ALWAYS PROVIDE THIS PARAMETER THIRD.
        new_str: The new substring. ALWAYS PROVIDE THIS PARAMETER FOURTH.
        replace_all: Whether to replace all occurrences of the substring. If False, only the first occurrence will be replaced. Default is False.
    '''
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        requested_path = path
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            validate_local_tool_path(path, thread_data)
            if not _is_custom_mount_path(path):
                path = _resolve_and_validate_user_data_path(path, thread_data)
        with get_file_operation_lock(sandbox, path):
            content = sandbox.read_file(path)
            if not content:
                if not old_str:
                    return "OK"
                return f"Error: String to replace not found in file: {requested_path}"
            if old_str not in content:
                return f"Error: String to replace not found in file: {requested_path}"
            if replace_all:
                content = content.replace(old_str, new_str)
            else:
                content = content.replace(old_str, new_str, 1)
            sandbox.write_file(path, content)
        return "OK"
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: File not found: {requested_path}"
    except PermissionError:
        return f"Error: Permission denied accessing file: {requested_path}"
    except Exception as e:
        return f"Error: Unexpected error replacing string: {_sanitize_error(e, runtime)}"


async def _str_replace_tool_async(
    runtime: Runtime,
    description: str,
    path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
) -> str:
    '''异步初始化沙箱后在线程中执行字符串替换工具。'''
    return await _run_sync_tool_after_async_sandbox_init(
        str_replace_tool.func,
        runtime,
        description,
        path,
        old_str,
        new_str,
        replace_all,
    )


str_replace_tool.coroutine = _str_replace_tool_async
