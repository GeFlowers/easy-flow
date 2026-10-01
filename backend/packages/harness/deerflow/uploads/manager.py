'''管理线程上传文件路径、无符号链接写入、目录清理及产物 URL。'''

import errno
import logging
import os
import re
import stat
from pathlib import Path
from urllib.parse import quote

from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from deerflow.runtime.user_context import get_effective_user_id


class PathTraversalError(ValueError):
    '''表示上传目标越出线程上传目录的路径穿越错误。'''


class UnsafeUploadPathError(ValueError):
    '''表示目标为符号链接、特殊文件或多硬链接等不安全上传位置。'''


logger = logging.getLogger(__name__)

# 线程标识仅允许字母、数字、点、连字符和下划线，以限制目录定位范围。
_SAFE_THREAD_ID = re.compile(r"^[a-zA-Z0-9._-]+$")
UPLOAD_STAGING_PREFIX = ".upload-"
UPLOAD_STAGING_SUFFIX = ".part"


def validate_thread_id(thread_id: str) -> None:
    '''校验线程标识，拒绝空值和可能影响目录结构的字符。'''
    if not thread_id or not _SAFE_THREAD_ID.match(thread_id):
        raise ValueError(f"Invalid thread_id: {thread_id!r}")


def get_uploads_dir(thread_id: str, *, user_id: str | None = None) -> Path:
    '''在当前用户隔离范围内返回线程上传目录。'''
    validate_thread_id(thread_id)
    return get_paths().sandbox_uploads_dir(thread_id, user_id=user_id or get_effective_user_id())


def ensure_uploads_dir(thread_id: str, *, user_id: str | None = None) -> Path:
    '''确保线程上传目录存在并返回其路径。'''
    base = get_uploads_dir(thread_id, user_id=user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize_filename(filename: str) -> str:
    '''剥离客户端提供的路径部分，并限制名称长度和路径分隔符。'''
    if not filename:
        raise ValueError("Filename is empty")
    safe = Path(filename).name
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {filename!r}")
    # Linux 不把反斜线视为路径分隔符，因此显式拒绝伪装成 Windows 路径的名称。
    if "\\" in safe:
        raise ValueError(f"Filename contains backslash: {filename!r}")
    if len(safe.encode("utf-8")) > 255:
        raise ValueError(f"Filename too long: {len(safe)} chars")
    return safe


def claim_unique_filename(name: str, seen: set[str]) -> str:
    '''在重名时追加递增序号，并把最终文件名登记到本批次集合。'''
    if name not in seen:
        seen.add(name)
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    candidate = f"{stem}_{counter}{suffix}"
    while candidate in seen:
        counter += 1
        candidate = f"{stem}_{counter}{suffix}"
    seen.add(candidate)
    return candidate


def is_upload_staging_file(filename: str) -> bool:
    '''识别尚未完成写入的临时上传文件，供启动清理逻辑过滤。'''
    return filename.startswith(UPLOAD_STAGING_PREFIX) and filename.endswith(UPLOAD_STAGING_SUFFIX)


def validate_path_traversal(path: Path, base: Path) -> None:
    '''确认目标解析后仍位于上传根目录内，否则抛出路径穿越错误。'''
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        raise PathTraversalError("Path traversal detected") from None


def validate_upload_destination(base_dir: Path, filename: str) -> Path:
    '''检查目标类型、硬链接数量和真实路径后返回安全写入位置。'''
    safe_name = normalize_filename(filename)
    dest = base_dir / safe_name

    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        st = None

    if st is not None and not stat.S_ISREG(st.st_mode):
        raise UnsafeUploadPathError(f"Upload destination is not a regular file: {safe_name}")
    if st is not None and st.st_nlink > 1:
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    validate_path_traversal(dest, base_dir)
    return dest


def _iter_upload_dirs(base_dir: Path):
    '''枚举共享布局和按用户隔离布局下的线程上传目录。'''
    yield from base_dir.glob("threads/*/user-data/uploads")
    yield from base_dir.glob("users/*/threads/*/user-data/uploads")


def cleanup_stale_upload_staging_files(base_dir: Path | str | None = None) -> int:
    '''清理进程异常退出后遗留的上传暂存文件，并返回删除数量。'''
    root = Path(base_dir) if base_dir is not None else get_paths().base_dir
    removed = 0
    for uploads_dir in _iter_upload_dirs(root):
        if not uploads_dir.is_dir():
            continue
        try:
            with os.scandir(uploads_dir) as entries:
                for entry in entries:
                    if not is_upload_staging_file(entry.name) or not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        os.unlink(entry.path)
                        removed += 1
                    except FileNotFoundError:
                        pass
                    except OSError:
                        logger.warning("Failed to remove stale upload staging file: %s", entry.path, exc_info=True)
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("Failed to scan uploads directory for stale staging files: %s", uploads_dir, exc_info=True)
    return removed


def open_upload_file_no_symlink(base_dir: Path, filename: str) -> tuple[Path, object]:
    '''尽可能以禁止跟随符号链接的方式创建或截断上传文件。'''
    safe_name = normalize_filename(filename)
    dest = validate_upload_destination(base_dir, safe_name)
    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        st = None

    has_nofollow = hasattr(os, "O_NOFOLLOW")

    if has_nofollow:
        # 支持 O_NOFOLLOW 的系统会在目标为符号链接时拒绝打开。
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK

        try:
            fd = os.open(dest, flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR, errno.ENOTDIR, errno.ENXIO, errno.EAGAIN}:
                raise UnsafeUploadPathError(f"Unsafe upload destination: {safe_name}") from exc
            raise

        try:
            opened_stat = os.fstat(fd)
            if not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_nlink != 1:
                raise UnsafeUploadPathError(f"Upload destination is not an exclusive regular file: {safe_name}")
            os.ftruncate(fd, 0)
            fh = os.fdopen(fd, "wb")
            fd = -1
        finally:
            if fd >= 0:
                os.close(fd)
        return dest, fh

    # Windows 没有 O_NOFOLLOW：打开前再次检查目标并在打开后核验文件描述符，
    # 以缩小检查与打开之间的竞态窗口；具备目录写权限的攻击者仍可能利用该窗口替换目标。
    if st is not None and st.st_nlink > 1:
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    flags = os.O_WRONLY | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    try:
        pre_open_st = os.lstat(dest)
    except FileNotFoundError:
        pre_open_st = None

    if pre_open_st is not None and not stat.S_ISREG(pre_open_st.st_mode):
        raise UnsafeUploadPathError(f"Upload destination is not a regular file: {safe_name}")
    if pre_open_st is not None and pre_open_st.st_nlink > 1:
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    try:
        fd = os.open(dest, flags, 0o600)
    except OSError as exc:
        if exc.errno in {errno.EISDIR, errno.ENOTDIR, errno.ENXIO, errno.EAGAIN}:
            raise UnsafeUploadPathError(f"Unsafe upload destination: {safe_name}") from exc
        raise

    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_nlink > 1:
            raise UnsafeUploadPathError(f"Upload destination is not an exclusive regular file: {safe_name}")
        os.ftruncate(fd, 0)
        fh = os.fdopen(fd, "wb")
        fd = -1
    finally:
        if fd >= 0:
            os.close(fd)
    return dest, fh


def write_upload_file_no_symlink(base_dir: Path, filename: str, data: bytes) -> Path:
    '''通过安全打开流程写入文件内容，并返回实际目标路径。'''
    dest, fh = open_upload_file_no_symlink(base_dir, filename)
    with fh:
        fh.write(data)
    return dest


def list_files_in_dir(directory: Path) -> dict:
    '''按名称排序列出普通文件，忽略符号链接和未完成上传的暂存文件。'''
    if not directory.is_dir():
        return {"files": [], "count": 0}

    files = []
    with os.scandir(directory) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if is_upload_staging_file(entry.name):
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            st = entry.stat(follow_symlinks=False)
            files.append(
                {
                    "filename": entry.name,
                    "size": st.st_size,
                    "path": entry.path,
                    "extension": Path(entry.name).suffix,
                    "modified": st.st_mtime,
                }
            )
    return {"files": files, "count": len(files)}


def delete_file_safe(base_dir: Path, filename: str, *, convertible_extensions: set[str] | None = None) -> dict:
    '''校验文件归属后删除上传文件，并按需清除转换生成的 Markdown 伴随文件。'''
    file_path = (base_dir / filename).resolve()
    validate_path_traversal(file_path, base_dir)

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {filename}")

    file_path.unlink()

    # 原文件被删除时同时清除上传转换阶段生成的 Markdown 副本。
    if convertible_extensions and file_path.suffix.lower() in convertible_extensions:
        file_path.with_suffix(".md").unlink(missing_ok=True)

    return {"success": True, "message": f"Deleted {filename}"}


def upload_artifact_url(thread_id: str, filename: str) -> str:
    '''生成前端读取线程上传文件所需的网关产物接口 URL。'''
    return f"/api/threads/{thread_id}/artifacts{VIRTUAL_PATH_PREFIX}/uploads/{quote(filename, safe='')}"


def upload_virtual_path(filename: str) -> str:
    '''生成沙箱命名空间内的上传文件虚拟路径。'''
    return f"{VIRTUAL_PATH_PREFIX}/uploads/{filename}"


def enrich_file_listing(result: dict, thread_id: str) -> dict:
    '''为文件列表补充沙箱虚拟路径和网关下载地址。'''
    for f in result["files"]:
        filename = f["filename"]
        f["virtual_path"] = upload_virtual_path(filename)
        f["artifact_url"] = upload_artifact_url(thread_id, filename)
    return result
