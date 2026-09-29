"""提供线程产物与技能归档文件的受权限保护下载接口。"""

import asyncio
import logging
import mimetypes
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.gateway.authz import require_permission
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.path_utils import resolve_thread_virtual_path
from deerflow.config.paths import make_safe_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["artifacts"])

ACTIVE_CONTENT_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
}

MAX_SKILL_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024
_SKILL_ARCHIVE_READ_CHUNK_SIZE = 64 * 1024


def _build_content_disposition(disposition_type: str, filename: str) -> str:
    """按照 RFC 5987 为指定文件名构造 Content-Disposition 响应头值。"""
    return f"{disposition_type}; filename*=UTF-8''{quote(filename)}"


def _build_attachment_headers(filename: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    """构造强制下载响应所需的头，并合并调用方提供的附加头。"""
    headers = {"Content-Disposition": _build_content_disposition("attachment", filename)}
    if extra_headers:
        headers.update(extra_headers)
    return headers


def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
    """通过抽样检查空字节判断文件是否可按文本安全返回。"""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
            # 文本文件通常不应包含空字节。
            return b"\x00" not in chunk
    except Exception:
        return False


def _read_skill_archive_member(zip_ref: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """读取 .skill 归档成员，并在解压前后强制执行大小上限。"""
    if info.file_size > MAX_SKILL_ARCHIVE_MEMBER_BYTES:
        raise HTTPException(status_code=413, detail="Skill archive member is too large to preview")

    chunks: list[bytes] = []
    total_read = 0
    with zip_ref.open(info, "r") as src:
        while chunk := src.read(_SKILL_ARCHIVE_READ_CHUNK_SIZE):
            total_read += len(chunk)
            if total_read > MAX_SKILL_ARCHIVE_MEMBER_BYTES:
                raise HTTPException(status_code=413, detail="Skill archive member is too large to preview")
            chunks.append(chunk)
    return b"".join(chunks)


def _extract_file_from_skill_archive(zip_path: Path, internal_path: str) -> bytes | None:
    """从 .skill ZIP 归档中提取指定文件。

    Args:
        zip_path: .skill 文件（ZIP 归档）的路径。
        internal_path: 归档内文件路径，例如 ``SKILL.md``。

    Returns:
        找到时返回文件字节；未找到时返回 ``None``。
    """
    if not zipfile.is_zipfile(zip_path):
        return None

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # 建立归档内全部文件的索引。
            infos_by_name = {info.filename: info for info in zip_ref.infolist()}

            # 先尝试完全匹配的路径。
            if internal_path in infos_by_name:
                return _read_skill_archive_member(zip_ref, infos_by_name[internal_path])

            # 再兼容带顶层目录前缀的路径，例如 ``skill-name/SKILL.md``。
            for name, info in infos_by_name.items():
                if name.endswith("/" + internal_path) or name == internal_path:
                    return _read_skill_archive_member(zip_ref, info)

            # 归档中不存在目标文件。
            return None
    except (zipfile.BadZipFile, KeyError):
        return None


def _load_skill_archive_member(actual_skill_path: Path, skill_file_path: str, internal_path: str) -> tuple[bytes, str | None]:
    """在工作线程中处理 ``get_artifact`` 的 ``.skill`` 归档分支。

    ``exists`` / ``is_file`` 探测、ZIP 打开与提取，以及 MIME 推断（``mimetypes``
    首次调用时会惰性读取系统 MIME 数据库）都会阻塞文件系统 I/O，必须脱离事件循环。
    抛出的 ``HTTPException`` 经 ``asyncio.to_thread`` 原样传播，因此状态码保持不变。
    """
    if not actual_skill_path.exists():
        raise HTTPException(status_code=404, detail=f"Skill file not found: {skill_file_path}")
    if not actual_skill_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {skill_file_path}")
    content = _extract_file_from_skill_archive(actual_skill_path, internal_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"File '{internal_path}' not found in skill archive")
    mime_type, _ = mimetypes.guess_type(internal_path)
    return content, mime_type


def _read_artifact_payload(actual_path: Path, path: str, download: bool) -> tuple[str, str | None, bytes | str | None]:
    """在工作线程中处理 ``get_artifact`` 的普通文件分支。

    文件状态探测、MIME 推断和整文件读取均会阻塞 I/O。函数返回
    ``(kind, mime_type, payload)`` 计划，由路由处理器在事件循环内生成响应：
    ``("file", mime, None)`` 交给 ``FileResponse`` 流式传输，或返回文本、字节内容。
    行为与错误状态码均与原内联逻辑一致。
    """
    if not actual_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {path}")
    if not actual_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")
    mime_type, _ = mimetypes.guess_type(actual_path)
    # 活动内容和显式下载由 FileResponse 流式发送，此处无需读取文件内容。
    if download or mime_type in ACTIVE_CONTENT_MIME_TYPES:
        return ("file", mime_type, None)
    if mime_type and mime_type.startswith("text/"):
        return ("text", mime_type, actual_path.read_text(encoding="utf-8"))
    if is_text_file_by_content(actual_path):
        return ("text", mime_type, actual_path.read_text(encoding="utf-8"))
    return ("bytes", mime_type, actual_path.read_bytes())


@router.get(
    "/threads/{thread_id}/artifacts/{path:path}",
    summary="Get Artifact File",
    description="Retrieve an artifact file generated by the AI agent. Text and binary files can be viewed inline, while active web content is always downloaded.",
)
@require_permission("threads", "read", owner_check=True)
async def get_artifact(thread_id: str, path: str, request: Request, download: bool = False) -> Response:
    """按虚拟路径读取线程产物，并在权限校验后选择安全的响应形式。

    路由自动识别文件类型并返回合适的内容类型；``download`` 可强制下载非活动内容。

    Args:
        thread_id: 线程标识。
        path: 带虚拟前缀的产物路径，例如 ``mnt/user-data/outputs/file.txt``。
        request: FastAPI 自动注入的请求对象。

    Returns:
        具有合适内容类型的文件响应：HTML/XHTML/SVG 始终下载，文本内联返回，
        二进制文件可内联展示或下载。

    Raises:
        HTTPException: 路径无效或非文件时为 400，越权或路径穿越时为 403，
            文件不存在时为 404。

    ``download`` 为真时，原本可内联的内容也作为附件下载；活动的 HTML/XHTML/SVG
    无论该参数为何值都强制下载，避免在应用源执行脚本。
    """
    # 可信内部调用方仅在内部令牌验证后，才能通过 owner-user-id 代表线程所有者。
    # 请求头携带平台原始所有者标识，而运行文件存于 make_safe_user_id 规范化后的桶中，
    # 因此路径解析使用规范化标识；浏览器/API 调用方得到 None 并回退到当前有效用户。
    raw_owner_user_id = get_trusted_internal_owner_user_id(request)
    owner_user_id = make_safe_user_id(raw_owner_user_id) if raw_owner_user_id else None

    # 判断是否请求 .skill 归档内的文件，例如 xxx.skill/SKILL.md。
    if ".skill/" in path:
        # 以 ".skill/" 分割，取得 ZIP 文件路径和归档内路径。
        skill_marker = ".skill/"
        marker_pos = path.find(skill_marker)
        skill_file_path = path[: marker_pos + len(".skill")]  # 例如 "mnt/user-data/outputs/my-skill.skill"
        internal_path = path[marker_pos + len(skill_marker) :]  # 例如 "SKILL.md"

        actual_skill_path = await asyncio.to_thread(resolve_thread_virtual_path, thread_id, skill_file_path, user_id=owner_user_id)

        # 将状态探测、ZIP 打开提取和 MIME 推断等阻塞 I/O 移至工作线程。
        content, mime_type = await asyncio.to_thread(_load_skill_archive_member, actual_skill_path, skill_file_path, internal_path)

        # 添加五分钟私有缓存，避免反复提取 ZIP。
        cache_headers = {"Cache-Control": "private, max-age=300"}
        download_name = Path(internal_path).name or actual_skill_path.stem
        if download or mime_type in ACTIVE_CONTENT_MIME_TYPES:
            return Response(content=content, media_type=mime_type or "application/octet-stream", headers=_build_attachment_headers(download_name, cache_headers))

        if mime_type and mime_type.startswith("text/"):
            return PlainTextResponse(content=content.decode("utf-8"), media_type=mime_type, headers=cache_headers)

        # 对看似文本的未知类型默认按纯文本返回。
        try:
            return PlainTextResponse(content=content.decode("utf-8"), media_type="text/plain", headers=cache_headers)
        except UnicodeDecodeError:
            return Response(content=content, media_type=mime_type or "application/octet-stream", headers=cache_headers)

    actual_path = await asyncio.to_thread(resolve_thread_virtual_path, thread_id, path, user_id=owner_user_id)

    logger.info(f"Resolving artifact path: thread_id={thread_id}, requested_path={path}, actual_path={actual_path}")

    # 将路径状态、MIME 推断和读取等阻塞 I/O 移至工作线程。活动内容和显式下载由
    # FileResponse 流式发送，因此工作线程仅报告类别；内联内容在其中读取。
    kind, mime_type, payload = await asyncio.to_thread(_read_artifact_payload, actual_path, path, download)

    if kind == "file":
        # 活动内容始终下载，避免用户打开产物时在应用源执行脚本。
        return FileResponse(path=actual_path, filename=actual_path.name, media_type=mime_type, headers=_build_attachment_headers(actual_path.name))

    if kind == "text":
        return PlainTextResponse(content=payload, media_type=mime_type)

    return Response(content=payload, media_type=mime_type, headers={"Content-Disposition": _build_content_disposition("inline", actual_path.name)})
