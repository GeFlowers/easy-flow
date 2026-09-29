"""定义 uploads 模块提供的职责与可复用接口。

Upload router for handling file uploads."""

import logging
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import SandboxProvider, get_sandbox_provider
from deerflow.uploads.manager import (
    UPLOAD_STAGING_PREFIX,
    UPLOAD_STAGING_SUFFIX,
    PathTraversalError,
    UnsafeUploadPathError,
    claim_unique_filename,
    delete_file_safe,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    normalize_filename,
    upload_artifact_url,
    upload_virtual_path,
    validate_upload_destination,
)
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/uploads", tags=["uploads"])

UPLOAD_CHUNK_SIZE = 8192
DEFAULT_MAX_FILES = 10
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024
DEFAULT_MAX_TOTAL_SIZE = 100 * 1024 * 1024


@dataclass(slots=True)
class _UploadTempFile:
    """保存单个上传文件提交前所需的目标路径、临时路径和已打开句柄。"""

    file_path: Path
    temp_path: Path
    handle: BinaryIO


class UploadedFileInfo(BaseModel):
    """描述单个上传文件的本地路径、沙箱路径及可选转换结果。"""

    filename: str
    size: int
    path: str
    virtual_path: str
    artifact_url: str
    extension: str | None = None
    modified: float | None = None
    original_filename: str | None = None
    markdown_file: str | None = None
    markdown_path: str | None = None
    markdown_virtual_path: str | None = None
    markdown_artifact_url: str | None = None


class UploadResponse(BaseModel):
    """汇总上传是否成功、已保存文件及跳过文件。"""

    success: bool
    files: list[UploadedFileInfo]
    message: str
    skipped_files: list[str] = Field(default_factory=list)


class UploadListResponse(BaseModel):
    """返回线程中的上传文件清单及文件数量。"""

    files: list[UploadedFileInfo]
    count: int


class UploadLimits(BaseModel):
    """向客户端公开单次数量、单文件大小和总上传大小上限。"""

    max_files: int
    max_file_size: int
    max_total_size: int


def _make_file_sandbox_writable(file_path: os.PathLike[str] | str) -> None:
    """为需要沙箱回写的上传文件补充读写权限，并拒绝跟随符号链接修改权限。"""
    file_stat = os.lstat(file_path)
    if stat.S_ISLNK(file_stat.st_mode):
        logger.warning("Skipping sandbox chmod for symlinked upload path: %s", file_path)
        return

    writable_mode = stat.S_IMODE(file_stat.st_mode) | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IRGRP | stat.S_IROTH
    chmod_kwargs = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}
    os.chmod(file_path, writable_mode, **chmod_kwargs)


def _make_file_sandbox_readable(file_path: os.PathLike[str] | str) -> None:
    """为沙箱进程补充组和其他用户的读取权限，不跟随符号链接改权限。"""
    file_stat = os.lstat(file_path)
    if stat.S_ISLNK(file_stat.st_mode):
        logger.warning("Skipping sandbox chmod for symlinked upload path: %s", file_path)
        return

    readable_mode = stat.S_IMODE(file_stat.st_mode) | stat.S_IRGRP | stat.S_IROTH
    chmod_kwargs = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}
    os.chmod(file_path, readable_mode, **chmod_kwargs)


def _uses_thread_data_mounts(sandbox_provider: SandboxProvider) -> bool:
    """判断沙箱提供方是否直接挂载线程数据而无需逐文件同步。"""
    return bool(getattr(sandbox_provider, "uses_thread_data_mounts", False))


def _get_uploads_config_value(app_config: AppConfig, key: str, default: object) -> object:
    """兼容字典和配置对象两种形式读取 uploads 子配置。"""
    uploads_cfg = getattr(app_config, "uploads", None)
    if isinstance(uploads_cfg, dict):
        return uploads_cfg.get(key, default)
    return getattr(uploads_cfg, key, default)


def _get_upload_limit(app_config: AppConfig, key: str, default: int, *, legacy_key: str | None = None) -> int:
    """读取单项上传限制，并兼容旧配置键及无效值回退。"""
    try:
        value = _get_uploads_config_value(app_config, key, None)
        if value is None and legacy_key is not None:
            value = _get_uploads_config_value(app_config, legacy_key, None)
        if value is None:
            value = default
        limit = int(value)
        if limit <= 0:
            raise ValueError
        return limit
    except Exception:
        logger.warning("Invalid uploads.%s value; falling back to %d", key, default)
        return default


def _get_upload_limits(app_config: AppConfig) -> UploadLimits:
    """从应用配置汇总每请求文件数、单文件和总大小限制。"""
    return UploadLimits(
        max_files=_get_upload_limit(app_config, "max_files", DEFAULT_MAX_FILES, legacy_key="max_file_count"),
        max_file_size=_get_upload_limit(app_config, "max_file_size", DEFAULT_MAX_FILE_SIZE, legacy_key="max_single_file_size"),
        max_total_size=_get_upload_limit(app_config, "max_total_size", DEFAULT_MAX_TOTAL_SIZE),
    )


def _cleanup_uploaded_paths(paths: list[os.PathLike[str] | str]) -> None:
    """按逆序尽力清理本次上传已落盘的路径，不覆盖原始异常。"""
    for path in reversed(paths):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("Failed to clean up upload path after rejected request: %s", path, exc_info=True)


def _prepare_upload_destination(uploads_dir: os.PathLike[str] | str, display_filename: str) -> _UploadTempFile:
    """验证目标文件名后创建同目录临时文件，供原子上传提交使用。"""
    uploads_dir_path = Path(uploads_dir)
    file_path = validate_upload_destination(uploads_dir_path, display_filename)
    temp_fd, temp_path_str = tempfile.mkstemp(prefix=UPLOAD_STAGING_PREFIX, suffix=UPLOAD_STAGING_SUFFIX, dir=uploads_dir_path)
    temp_path = Path(temp_path_str)
    try:
        handle = os.fdopen(temp_fd, "wb")
    except Exception:
        try:
            os.close(temp_fd)
        except OSError:
            pass
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
    return _UploadTempFile(file_path=file_path, temp_path=temp_path, handle=handle)


def _write_upload_chunk(upload_temp: _UploadTempFile, chunk: bytes) -> None:
    """将一个上传数据块写入尚未提交的临时文件。"""
    upload_temp.handle.write(chunk)


def _abort_upload_temp(upload_temp: _UploadTempFile) -> None:
    """关闭并删除未提交的临时上传文件。"""
    try:
        upload_temp.handle.close()
    finally:
        try:
            os.unlink(upload_temp.temp_path)
        except FileNotFoundError:
            pass


def _commit_upload_temp(upload_temp: _UploadTempFile) -> None:
    """关闭临时文件并原子替换最终上传目标。"""
    upload_temp.handle.close()
    try:
        os.replace(upload_temp.temp_path, upload_temp.file_path)
    except Exception:
        try:
            os.unlink(upload_temp.temp_path)
        except FileNotFoundError:
            pass
        raise


def _make_uploaded_paths_sandbox_readable(paths: list[os.PathLike[str] | str]) -> None:
    """调整已上传文件权限，使沙箱进程能够读取它们。"""
    for file_path in paths:
        _make_file_sandbox_readable(file_path)


def _sync_upload_to_sandbox(sandbox, file_path: os.PathLike[str] | str, virtual_path: str) -> None:
    """将本地上传文件同步至未挂载线程数据的沙箱虚拟路径。"""
    _make_file_sandbox_writable(file_path)
    sandbox.update_file(virtual_path, Path(file_path).read_bytes())


def _list_uploaded_files_for_thread(thread_id: str, user_id: str) -> dict:
    """列出指定用户在线程隔离上传目录中的文件。"""
    uploads_dir = get_uploads_dir(thread_id, user_id=user_id)
    result = list_files_in_dir(uploads_dir)
    enrich_file_listing(result, thread_id)

    sandbox_uploads = get_paths().sandbox_uploads_dir(thread_id, user_id=user_id)
    for f in result["files"]:
        f["path"] = str(sandbox_uploads / f["filename"])
    return result


def _delete_uploaded_file_for_thread(thread_id: str, filename: str, user_id: str) -> dict:
    """从指定用户的线程上传目录安全删除一个已上传文件。"""
    uploads_dir = get_uploads_dir(thread_id, user_id=user_id)
    return delete_file_safe(uploads_dir, filename, convertible_extensions=CONVERTIBLE_EXTENSIONS)


async def _write_upload_file_with_limits(
    file: UploadFile,
    *,
    uploads_dir: os.PathLike[str] | str,
    display_filename: str,
    max_single_file_size: int,
    max_total_size: int,
    total_size: int,
) -> tuple[os.PathLike[str] | str, int, int]:
    """分块写入上传内容并实时校验单文件和总量限制，失败时清理临时文件。"""
    file_size = 0
    upload_temp: _UploadTempFile | None = None
    try:
        upload_temp = await run_file_io(_prepare_upload_destination, uploads_dir, display_filename)
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            file_size += len(chunk)
            total_size += len(chunk)
            if file_size > max_single_file_size:
                raise HTTPException(status_code=413, detail=f"File too large: {display_filename}")
            if total_size > max_total_size:
                raise HTTPException(status_code=413, detail="Total upload size too large")
            await run_file_io(_write_upload_chunk, upload_temp, chunk)

        await run_file_io(_commit_upload_temp, upload_temp)
        file_path = upload_temp.file_path
        upload_temp = None
    except Exception:
        if upload_temp is not None:
            await run_file_io(_abort_upload_temp, upload_temp)
        raise
    return file_path, file_size, total_size


def _auto_convert_documents_enabled(app_config: AppConfig) -> bool:
    """读取文档自动转换开关；仅显式启用时执行，配置异常时默认关闭。"""
    try:
        raw = _get_uploads_config_value(app_config, "auto_convert_documents", False)
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
    except Exception:
        return False


@router.post("", response_model=UploadResponse)
@require_permission("threads", "write", owner_check=True, require_existing=False)
async def upload_files(
    thread_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
    config: AppConfig = Depends(get_config),
) -> UploadResponse:
    """校验并保存多份线程附件，必要时转换文档并同步到非挂载型沙箱。"""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    limits = _get_upload_limits(config)
    if len(files) > limits.max_files:
        raise HTTPException(status_code=413, detail=f"Too many files: maximum is {limits.max_files}")

    try:
        effective_user_id = get_effective_user_id()
        uploads_dir = await run_file_io(ensure_uploads_dir, thread_id, user_id=effective_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sandbox_uploads = uploads_dir
    uploaded_files = []
    written_paths = []
    sandbox_sync_targets = []
    skipped_files = []
    total_size = 0
    # 防止同一请求中的重名表单项互相覆盖；单文件替换已有上传仍沿用覆盖行为。
    seen_filenames: set[str] = set()

    sandbox_provider = get_sandbox_provider()
    sync_to_sandbox = not _uses_thread_data_mounts(sandbox_provider)
    sandbox = None
    if sync_to_sandbox:
        sandbox_id = await sandbox_provider.acquire_async(thread_id, user_id=effective_user_id)
        sandbox = sandbox_provider.get(sandbox_id)
        if sandbox is None:
            raise HTTPException(status_code=500, detail="Failed to acquire sandbox")
    auto_convert_documents = _auto_convert_documents_enabled(config)

    for file in files:
        if not file.filename:
            continue

        try:
            original_filename = normalize_filename(file.filename)
            safe_filename = claim_unique_filename(original_filename, seen_filenames)
        except ValueError:
            logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
            continue

        try:
            file_path, file_size, total_size = await _write_upload_file_with_limits(
                file,
                uploads_dir=uploads_dir,
                display_filename=safe_filename,
                max_single_file_size=limits.max_file_size,
                max_total_size=limits.max_total_size,
                total_size=total_size,
            )
            written_paths.append(file_path)

            virtual_path = upload_virtual_path(safe_filename)

            if sync_to_sandbox:
                sandbox_sync_targets.append((file_path, virtual_path))

            file_info = {
                "filename": safe_filename,
                "size": file_size,
                "path": str(sandbox_uploads / safe_filename),
                "virtual_path": virtual_path,
                "artifact_url": upload_artifact_url(thread_id, safe_filename),
            }
            if safe_filename != original_filename:
                file_info["original_filename"] = original_filename

            logger.info(f"Saved file: {safe_filename} ({file_size} bytes) to {file_info['path']}")

            file_ext = file_path.suffix.lower()
            if auto_convert_documents and file_ext in CONVERTIBLE_EXTENSIONS:
                md_path = await convert_file_to_markdown(file_path)
                if md_path:
                    written_paths.append(md_path)
                    md_virtual_path = upload_virtual_path(md_path.name)

                    if sync_to_sandbox:
                        sandbox_sync_targets.append((md_path, md_virtual_path))

                    file_info["markdown_file"] = md_path.name
                    file_info["markdown_path"] = str(sandbox_uploads / md_path.name)
                    file_info["markdown_virtual_path"] = md_virtual_path
                    file_info["markdown_artifact_url"] = upload_artifact_url(thread_id, md_path.name)

            uploaded_files.append(file_info)

        except HTTPException as e:
            await run_file_io(_cleanup_uploaded_paths, written_paths)
            raise e
        except UnsafeUploadPathError as e:
            logger.warning("Skipping upload with unsafe destination %s: %s", file.filename, e)
            skipped_files.append(safe_filename)
            continue
        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            await run_file_io(_cleanup_uploaded_paths, written_paths)
            raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {str(e)}")

    # 上传文件默认权限为 0o600；Docker 沙箱通常以非 root 用户运行。
    # 无论目录挂载还是逐文件同步，都需要组和其他用户读取位才能让沙箱访问。
    await run_file_io(_make_uploaded_paths_sandbox_readable, written_paths)

    if sync_to_sandbox:
        for file_path, virtual_path in sandbox_sync_targets:
            await run_file_io(_sync_upload_to_sandbox, sandbox, file_path, virtual_path)

    message = f"Successfully uploaded {len(uploaded_files)} file(s)"
    if skipped_files:
        message += f"; skipped {len(skipped_files)} unsafe file(s)"

    return UploadResponse(
        success=not skipped_files,
        files=uploaded_files,
        message=message,
        skipped_files=skipped_files,
    )


@router.get("/limits", response_model=UploadLimits)
@require_permission("threads", "read", owner_check=True)
async def get_upload_limits(
    thread_id: str,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> UploadLimits:
    """返回当前线程上传接口允许的文件大小和数量限制。"""
    return _get_upload_limits(config)


@router.get("/list", response_model=UploadListResponse)
@require_permission("threads", "read", owner_check=True)
async def list_uploaded_files(thread_id: str, request: Request) -> UploadListResponse:
    """列出当前线程上传目录中可见的文件及其元数据。"""
    try:
        result = await run_file_io(_list_uploaded_files_for_thread, thread_id, get_effective_user_id())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return UploadListResponse(**result)


@router.delete("/{filename}")
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_uploaded_file(thread_id: str, filename: str, request: Request) -> dict:
    """删除当前线程上传目录中的指定文件。"""
    try:
        return await run_file_io(_delete_uploaded_file_for_thread, thread_id, filename, get_effective_user_id())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except PathTraversalError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")
