'''安全校验并安装技能目录或压缩包，在安装前阻止越界路径、可执行载荷和危险内容。'''

import asyncio
import concurrent.futures
import logging
import posixpath
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from deerflow.skills.permissions import make_skill_tree_sandbox_readable
from deerflow.skills.security_scanner import scan_skill_content
from deerflow.skills.security_static_scanner import (
    StaticFinding,
    StaticScanBlockedError,
    StaticScannerError,
    enforce_static_scan,
    scan_archive_preflight,
    skill_scan_enabled,
)

logger = logging.getLogger(__name__)

_PROMPT_INPUT_DIRS = {"references", "templates"}
_PROMPT_INPUT_SUFFIXES = frozenset({".json", ".markdown", ".md", ".rst", ".txt", ".yaml", ".yml"})
_CODE_SUFFIXES = frozenset({".bash", ".cjs", ".js", ".mjs", ".php", ".pl", ".ps1", ".py", ".rb", ".sh", ".ts", ".zsh"})
_EXECUTABLE_MAGIC_PREFIXES = (
    b"\x7fELF",
    b"MZ",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
)


class SkillAlreadyExistsError(ValueError):
    '''目标技能目录已存在时抛出，避免静默覆盖用户已有技能。'''


class SkillSecurityScanError(ValueError):
    '''技能静态或内容扫描拒绝安装时抛出，并携带相关发现和技能名称。'''

    findings: list[StaticFinding]
    skill_name: str | None

    def __init__(self, message: str, *, findings: list[StaticFinding] | None = None, skill_name: str | None = None) -> None:
        '''保存安全扫描拒绝原因、发现详情及对应技能名称。'''
        super().__init__(message)
        self.findings = [dict(finding) for finding in (findings or [])]
        self.skill_name = skill_name


def is_unsafe_zip_member(info: zipfile.ZipInfo) -> bool:
    '''检查压缩包成员是否使用绝对路径或目录穿越路径。'''
    name = info.filename
    if not name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return True
    if PureWindowsPath(name).is_absolute():
        return True
    if ".." in path.parts:
        return True
    return False


def is_symlink_member(info: zipfile.ZipInfo) -> bool:
    '''根据压缩包成员的 Unix 权限位识别符号链接。'''
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def is_executable_binary_prefix(prefix: bytes) -> bool:
    '''根据可执行文件的魔数前缀判断压缩包成员是否为二进制程序。'''
    return prefix.startswith(_EXECUTABLE_MAGIC_PREFIXES)


def should_ignore_archive_entry(path: Path) -> bool:
    '''忽略隐藏文件和 macOS 压缩包附带的元数据目录。'''
    return path.name.startswith(".") or path.name == "__MACOSX"


def resolve_skill_dir_from_archive(temp_path: Path) -> Path:
    '''定位压缩包中的技能根目录；若归档只有一个有效顶层目录则使用该目录。'''
    items = [p for p in temp_path.iterdir() if not should_ignore_archive_entry(p)]
    if not items:
        raise ValueError("Skill archive is empty")
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return temp_path


def safe_extract_skill_archive(
    zip_ref: zipfile.ZipFile,
    dest_path: Path,
    max_total_size: int = 512 * 1024 * 1024,
) -> None:
    '''逐项校验并解压技能归档，拒绝符号链接、可执行二进制、越界路径和超大内容。'''
    dest_root = dest_path.resolve()
    total_written = 0

    for info in zip_ref.infolist():
        if is_unsafe_zip_member(info):
            raise ValueError(f"Archive contains unsafe member path: {info.filename!r}")

        if is_symlink_member(info):
            logger.warning("Skipping symlink entry in skill archive: %s", info.filename)
            continue

        normalized_name = posixpath.normpath(info.filename.replace("\\", "/"))
        member_path = dest_root.joinpath(*PurePosixPath(normalized_name).parts)
        if not member_path.resolve().is_relative_to(dest_root):
            raise ValueError(f"Zip entry escapes destination: {info.filename!r}")
        member_path.parent.mkdir(parents=True, exist_ok=True)

        if info.is_dir():
            member_path.mkdir(parents=True, exist_ok=True)
            continue

        with zip_ref.open(info) as src, member_path.open("wb") as dst:
            first_chunk = True
            while chunk := src.read(65536):
                if first_chunk and is_executable_binary_prefix(chunk):
                    raise ValueError(f"Archive contains executable binary member: {info.filename!r}")
                first_chunk = False
                total_written += len(chunk)
                if total_written > max_total_size:
                    raise ValueError("Skill archive is too large or appears highly compressed.")
                dst.write(chunk)


def _is_script_support_file(rel_path: Path) -> bool:
    '''判断文件是否位于技能的脚本支持目录中。'''
    return bool(rel_path.parts) and rel_path.parts[0] == "scripts"


def _should_scan_support_file(rel_path: Path) -> bool:
    '''决定脚本、参考资料和模板类文本是否需要内容安全扫描。'''
    if _is_script_support_file(rel_path):
        return True
    return bool(rel_path.parts) and rel_path.parts[0] in _PROMPT_INPUT_DIRS and rel_path.suffix.lower() in _PROMPT_INPUT_SUFFIXES


def _has_shebang(path: Path) -> bool:
    '''检查文件开头是否具有可执行脚本标记。'''
    try:
        with path.open("rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def _is_code_file_by_name(rel_path: Path) -> bool:
    '''根据脚本目录或文件扩展名判断路径是否属于代码文件。'''
    if _is_script_support_file(rel_path):
        return True
    return rel_path.suffix.lower() in _CODE_SUFFIXES


async def _is_code_file(path: Path, rel_path: Path) -> bool:
    '''结合文件名和脚本标记识别无扩展名的可执行文件。'''
    if _is_code_file_by_name(rel_path):
        return True
    return not rel_path.suffix and await asyncio.to_thread(_has_shebang, path)


def _move_staged_skill_into_reserved_target(staging_target: Path, target: Path) -> None:
    '''将暂存技能移动到已预留的目标目录，完成后设置只读权限，失败时清理预留目录。'''
    installed = False
    reserved = False
    try:
        target.mkdir(mode=0o700)
        reserved = True
        for child in staging_target.iterdir():
            shutil.move(str(child), target / child.name)
        make_skill_tree_sandbox_readable(target)
        installed = True
    except FileExistsError as e:
        raise SkillAlreadyExistsError(f"Skill '{target.name}' already exists") from e
    finally:
        if reserved and not installed and target.exists():
            shutil.rmtree(target)


def _findings_for_file(findings: list[StaticFinding], rel_path: str) -> list[StaticFinding]:
    '''筛选出与指定技能文件相关的静态扫描发现，同时保留全局发现。'''
    return [finding for finding in findings if finding.get("file") in {rel_path, None}]


async def _scan_skill_file_or_raise(skill_dir: Path, path: Path, skill_name: str, *, executable: bool, static_findings: list[StaticFinding] | None = None) -> None:
    '''读取技能文件并执行内容扫描；无效编码、扫描异常或拒绝结果均转为安装安全错误。'''
    rel_path = path.relative_to(skill_dir).as_posix()
    location = f"{skill_name}/{rel_path}"
    try:
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except UnicodeDecodeError as e:
        raise SkillSecurityScanError(f"Security scan failed for skill '{skill_name}': {location} must be valid UTF-8") from e

    try:
        result = await scan_skill_content(content, executable=executable, location=location, static_findings=static_findings or [])
    except Exception as e:
        raise SkillSecurityScanError(f"Security scan failed for {location}: {e}") from e

    decision = getattr(result, "decision", None)
    reason = str(getattr(result, "reason", "") or "No reason provided.")
    if decision == "block":
        if rel_path == "SKILL.md":
            raise SkillSecurityScanError(f"Security scan blocked skill '{skill_name}': {reason}")
        raise SkillSecurityScanError(f"Security scan blocked {location}: {reason}")
    if executable and decision != "allow":
        raise SkillSecurityScanError(f"Security scan rejected executable {location}: {reason}")
    if decision not in {"allow", "warn"}:
        raise SkillSecurityScanError(f"Security scan failed for {location}: invalid scanner decision {decision!r}")


def scan_archive_preflight_or_raise(archive_path: Path, *, app_config=None) -> None:
    '''在安全扫描启用时检查整个压缩包，并对严重问题立即中止安装。'''
    if not skill_scan_enabled(app_config):
        return
    result = scan_archive_preflight(archive_path)
    if result["blocked"]:
        critical = [finding for finding in result["findings"] if finding["severity"] == "CRITICAL"]
        raise SkillSecurityScanError(
            f"Static security scan blocked unsafe skill archive: {format_static_archive_findings(critical)}",
            findings=critical,
            skill_name=None,
        )


def format_static_archive_findings(findings: list[StaticFinding]) -> str:
    '''把压缩包扫描发现整理为包含规则、等级、文件和原因的可读文本。'''
    return "; ".join(f"{finding['rule_id']} ({finding['severity']}) at {finding.get('file') or '<archive>'}: {finding['message']}" for finding in findings)


async def _scan_static_skill_archive_or_raise(skill_dir: Path, skill_name: str, *, app_config=None) -> list[StaticFinding]:
    '''在线程池中执行目录级静态扫描，并将扫描阻断或内部失败统一包装为安装错误。'''
    try:
        return await asyncio.to_thread(enforce_static_scan, skill_dir, skill_name=skill_name, app_config=app_config)
    except StaticScanBlockedError as e:
        raise SkillSecurityScanError(str(e), findings=e.findings, skill_name=e.skill_name) from e
    except StaticScannerError as e:
        raise SkillSecurityScanError(f"Static security scan failed for skill '{skill_name}': {e}", skill_name=skill_name) from e


def _collect_scannable_files(skill_dir: Path) -> list[Path]:
    '''按路径排序收集技能目录内的普通文件，供后续逐项扫描。'''
    return [candidate for candidate in sorted(skill_dir.rglob("*")) if candidate.is_file()]


async def _scan_skill_archive_contents_or_raise(skill_dir: Path, skill_name: str, *, app_config=None) -> list[StaticFinding]:
    '''先扫描技能目录，再校验入口说明、脚本及提示资料，并拒绝嵌套技能入口文件。'''
    static_findings = await _scan_static_skill_archive_or_raise(skill_dir, skill_name, app_config=app_config)

    skill_md = skill_dir / "SKILL.md"
    await _scan_skill_file_or_raise(skill_dir, skill_md, skill_name, executable=False, static_findings=_findings_for_file(static_findings, "SKILL.md"))

    for path in await asyncio.to_thread(_collect_scannable_files, skill_dir):
        rel_path = path.relative_to(skill_dir)
        if rel_path == Path("SKILL.md"):
            continue
        if path.name == "SKILL.md":
            raise SkillSecurityScanError(f"Security scan failed for skill '{skill_name}': nested SKILL.md is not allowed at {skill_name}/{rel_path.as_posix()}")
        rel_path_posix = rel_path.as_posix()
        if await _is_code_file(path, rel_path):
            await _scan_skill_file_or_raise(
                skill_dir,
                path,
                skill_name,
                executable=True,
                static_findings=_findings_for_file(static_findings, rel_path_posix),
            )
        elif _should_scan_support_file(rel_path):
            await _scan_skill_file_or_raise(
                skill_dir,
                path,
                skill_name,
                executable=False,
                static_findings=_findings_for_file(static_findings, rel_path_posix),
            )
    return static_findings


def _run_async_install(coro):
    '''在已有事件循环中通过独立工作线程运行安装协程，否则直接启动临时事件循环。'''
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
