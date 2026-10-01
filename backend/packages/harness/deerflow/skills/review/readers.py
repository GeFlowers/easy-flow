'''读取本地目录、技能压缩包或内联说明，并生成受大小与路径安全限制的审查快照。'''

from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from deerflow.skills.review.models import (
    DEFAULT_PACKAGE_LIMITS,
    PACKAGE_SNAPSHOT_SCHEMA_VERSION,
    PackageLimits,
    normalize_relative_path,
)

_TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
_ZIP_READ_CHUNK_BYTES = 1024 * 1024


def _sha256(data: bytes) -> str:
    '''计算字节内容的 SHA-256 摘要，供快照识别文件内容。'''
    return hashlib.sha256(data).hexdigest()


def _decode_text(data: bytes, path: str) -> str | None:
    '''仅将可识别文本文件按 UTF-8 解码，避免把二进制内容误送入文本分析器。'''
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in _TEXT_EXTENSIONS and b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _truncate_utf8_bytes(content: str, max_bytes: int) -> tuple[str, bytes]:
    '''按字节上限截断 UTF-8 文本，并移除不完整的尾部字符序列。'''
    data = content.encode("utf-8")
    truncated = data[:max_bytes]
    text = truncated.decode("utf-8", errors="ignore")
    return text, text.encode("utf-8")


def _subject(
    *,
    source: str,
    display_ref: str,
    name_hint: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    '''构造描述技能来源、分类及展示标识的快照主体信息。'''
    return {
        "source": source,
        "category": category,
        "name_hint": name_hint,
        "display_ref": display_ref,
    }


def _empty_snapshot(subject: dict[str, Any], limits: PackageLimits) -> dict[str, Any]:
    '''初始化统一快照结构，使不同读取器返回相同字段和限制信息。'''
    return {
        "schema_version": PACKAGE_SNAPSHOT_SCHEMA_VERSION,
        "subject": subject,
        "limits": limits.to_dict(),
        "files": [],
        "truncated": False,
        "reader_errors": [],
    }


def build_inline_snapshot(
    content: str,
    *,
    name_hint: str | None = None,
    limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
) -> dict[str, Any]:
    '''把调用方直接提供的技能说明包装为单文件快照，并应用单文件字节上限。'''
    data = content.encode("utf-8")
    snapshot = _empty_snapshot(
        _subject(source="inline", display_ref=name_hint or "inline://SKILL.md", name_hint=name_hint),
        limits,
    )
    if len(data) > limits.max_file_bytes:
        snapshot["truncated"] = True
        snapshot["reader_errors"].append(
            {
                "code": "file_too_large",
                "path": "SKILL.md",
                "message": "Inline SKILL.md exceeds the per-file review limit",
            }
        )
        content, data = _truncate_utf8_bytes(content, limits.max_file_bytes)

    snapshot["files"].append(
        {
            "path": "SKILL.md",
            "kind": "text",
            "size": len(data),
            "sha256": _sha256(data),
            "content": content,
        }
    )
    return snapshot


class LocalDirectoryReader:
    '''安全枚举本地技能目录；不跟随符号链接，并记录越界、读取失败和资源超限情况。'''

    def __init__(
        self,
        root: str | Path,
        *,
        subject: dict[str, Any] | None = None,
        limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    ) -> None:
        '''保存待读取目录、快照来源信息和本次读取所用的资源限制。'''
        self.root = Path(root)
        self.limits = limits
        self.subject = subject or _subject(
            source="local_directory",
            display_ref=self.root.name or str(self.root),
            name_hint=self.root.name or None,
        )

    def read(self) -> dict[str, Any]:
        '''逐项读取目录内容，标记文本、二进制及符号链接，并在越过限制时提前结束。'''
        root = self.root
        snapshot = _empty_snapshot(self.subject, self.limits)
        if not root.exists():
            snapshot["reader_errors"].append({"code": "root_not_found", "path": None, "message": "Package root does not exist"})
            return snapshot
        if not root.is_dir():
            snapshot["reader_errors"].append({"code": "root_not_directory", "path": None, "message": "Package root is not a directory"})
            return snapshot

        root_resolved = root.resolve()
        total_bytes = 0
        file_count = 0

        for current_root, dir_names, file_names in os.walk(root_resolved, followlinks=False):
            current = Path(current_root)
            dir_names[:] = sorted(dir_names)
            file_names = sorted(file_names)

            for dirname in list(dir_names):
                path = current / dirname
                if not path.is_symlink():
                    continue
                dir_names.remove(dirname)
                file_count = self._append_symlink(snapshot, path, root_resolved, file_count)

            for filename in file_names:
                path = current / filename
                if path.is_symlink():
                    file_count = self._append_symlink(snapshot, path, root_resolved, file_count)
                    continue

                rel_path = self._relative(path, root_resolved, snapshot)
                if rel_path is None:
                    continue
                file_count += 1
                if file_count > self.limits.max_files:
                    snapshot["truncated"] = True
                    snapshot["reader_errors"].append({"code": "too_many_files", "path": None, "message": "Package file count exceeds the review limit"})
                    return self._sort_snapshot(snapshot)

                try:
                    size = path.stat().st_size
                except OSError as exc:
                    snapshot["reader_errors"].append({"code": "stat_failed", "path": rel_path, "message": str(exc)})
                    continue

                total_bytes += max(size, 0)
                if total_bytes > self.limits.max_total_bytes:
                    snapshot["truncated"] = True
                    snapshot["reader_errors"].append({"code": "total_size_exceeded", "path": rel_path, "message": "Package total size exceeds the review limit"})
                    return self._sort_snapshot(snapshot)

                if size > self.limits.max_file_bytes:
                    snapshot["truncated"] = True
                    snapshot["files"].append({"path": rel_path, "kind": "binary", "size": size, "sha256": "", "content": None})
                    snapshot["reader_errors"].append({"code": "file_too_large", "path": rel_path, "message": "File exceeds the per-file review limit"})
                    continue

                try:
                    data = path.read_bytes()
                except OSError as exc:
                    snapshot["reader_errors"].append({"code": "read_failed", "path": rel_path, "message": str(exc)})
                    continue

                text = _decode_text(data, rel_path)
                entry: dict[str, Any] = {
                    "path": rel_path,
                    "kind": "text" if text is not None else "binary",
                    "size": len(data),
                    "sha256": _sha256(data),
                }
                if text is not None:
                    entry["content"] = text
                snapshot["files"].append(entry)

        return self._sort_snapshot(snapshot)

    def _append_symlink(self, snapshot: dict[str, Any], path: Path, root: Path, file_count: int) -> int:
        '''将符号链接作为独立快照条目记录目标摘要，不访问链接指向的内容。'''
        rel_path = self._relative(path, root, snapshot)
        if rel_path is None:
            return file_count
        file_count += 1
        if file_count > self.limits.max_files:
            snapshot["truncated"] = True
            snapshot["reader_errors"].append({"code": "too_many_files", "path": None, "message": "Package file count exceeds the review limit"})
            return file_count
        try:
            target = os.readlink(path)
        except OSError:
            target = ""
        snapshot["files"].append(
            {
                "path": rel_path,
                "kind": "symlink",
                "size": 0,
                "sha256": _sha256(target.encode("utf-8")),
                "target": target,
            }
        )
        return file_count

    @staticmethod
    def _relative(path: Path, root: Path, snapshot: dict[str, Any]) -> str | None:
        '''把目录项转换为根目录内的规范相对路径；越界项写入读取错误并跳过。'''
        try:
            rel = path.relative_to(root).as_posix()
            return normalize_relative_path(rel)
        except ValueError:
            snapshot["reader_errors"].append({"code": "path_escaped", "path": None, "message": "Package entry escapes the root"})
            return None

    @staticmethod
    def _sort_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        '''按路径和错误代码排序快照，确保相同输入产生稳定输出。'''
        snapshot["files"] = sorted(snapshot["files"], key=lambda item: item["path"])
        snapshot["reader_errors"] = sorted(snapshot["reader_errors"], key=lambda item: (str(item.get("path") or ""), str(item.get("code") or "")))
        return snapshot


class ArchivePackageReader:
    '''直接检查技能 ZIP 压缩包内容，不解压到磁盘，并限制成员数量和解压读取量。'''

    def __init__(
        self,
        archive_path: str | Path,
        *,
        limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    ) -> None:
        '''保存压缩包路径及读取该包时使用的资源限制。'''
        self.archive_path = Path(archive_path)
        self.limits = limits

    def read(self) -> dict[str, Any]:
        '''有界读取压缩包成员，识别符号链接和文本文件，并收集损坏或超限错误。'''
        snapshot = _empty_snapshot(
            _subject(source="archive", display_ref=str(self.archive_path.name), name_hint=self.archive_path.stem),
            self.limits,
        )
        try:
            with zipfile.ZipFile(self.archive_path, "r") as zf:
                total_bytes = 0
                members = sorted(zf.infolist(), key=lambda info: info.filename)
                if len(members) > self.limits.max_files:
                    snapshot["truncated"] = True
                    snapshot["reader_errors"].append({"code": "too_many_files", "path": None, "message": "Archive member count exceeds the review limit"})
                    members = members[: self.limits.max_files]
                for info in members:
                    if info.is_dir():
                        continue
                    rel_path = self._normalize_archive_name(info.filename, snapshot)
                    if rel_path is None:
                        continue

                    declared_size = max(info.file_size, 0)
                    if declared_size > self.limits.max_file_bytes:
                        snapshot["truncated"] = True
                        snapshot["files"].append({"path": rel_path, "kind": "binary", "size": declared_size, "sha256": "", "content": None})
                        snapshot["reader_errors"].append({"code": "file_too_large", "path": rel_path, "message": "Archive member exceeds the per-file review limit"})
                        continue

                    remaining_total_bytes = self.limits.max_total_bytes - total_bytes
                    if remaining_total_bytes <= 0:
                        snapshot["truncated"] = True
                        snapshot["reader_errors"].append({"code": "total_size_exceeded", "path": rel_path, "message": "Archive total size exceeds the review limit"})
                        break

                    member_budget = min(self.limits.max_file_bytes, remaining_total_bytes)
                    try:
                        data, actual_size, limit_exceeded = _read_zip_member_bounded(zf, info, max_bytes=member_budget)
                    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                        snapshot["reader_errors"].append({"code": "archive_member_read_failed", "path": rel_path, "message": str(exc)})
                        continue

                    if limit_exceeded:
                        snapshot["truncated"] = True
                        if actual_size > self.limits.max_file_bytes:
                            snapshot["files"].append({"path": rel_path, "kind": "binary", "size": actual_size, "sha256": "", "content": None})
                            snapshot["reader_errors"].append({"code": "file_too_large", "path": rel_path, "message": "Archive member exceeds the per-file review limit"})
                            continue
                        snapshot["reader_errors"].append({"code": "total_size_exceeded", "path": rel_path, "message": "Archive total size exceeds the review limit"})
                        break

                    total_bytes += actual_size
                    if _zip_member_is_symlink(info):
                        target = data.decode("utf-8", errors="replace")
                        snapshot["files"].append({"path": rel_path, "kind": "symlink", "size": 0, "sha256": _sha256(data), "target": target})
                        continue
                    text = _decode_text(data, rel_path)
                    entry: dict[str, Any] = {
                        "path": rel_path,
                        "kind": "text" if text is not None else "binary",
                        "size": actual_size,
                        "sha256": _sha256(data),
                    }
                    if text is not None:
                        entry["content"] = text
                    snapshot["files"].append(entry)
        except (OSError, zipfile.BadZipFile) as exc:
            snapshot["reader_errors"].append({"code": "archive_read_failed", "path": None, "message": str(exc)})

        snapshot["files"] = sorted(snapshot["files"], key=lambda item: item["path"])
        snapshot["reader_errors"] = sorted(snapshot["reader_errors"], key=lambda item: (str(item.get("path") or ""), str(item.get("code") or "")))
        return snapshot

    @staticmethod
    def _normalize_archive_name(filename: str, snapshot: dict[str, Any]) -> str | None:
        '''校验压缩包成员名并转换为安全相对路径，拒绝绝对路径及目录穿越路径。'''
        try:
            return normalize_relative_path(filename)
        except ValueError as exc:
            snapshot["reader_errors"].append({"code": "invalid_archive_path", "path": filename, "message": str(exc)})
            return None


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    '''根据 ZIP 成员的 Unix 文件模式判断其是否为符号链接。'''
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _read_zip_member_bounded(zf: zipfile.ZipFile, info: zipfile.ZipInfo, *, max_bytes: int) -> tuple[bytes, int, bool]:
    '''分块读取 ZIP 成员，最多读取上限加一个字节以识别超限而避免无界解压。'''
    chunks: list[bytes] = []
    actual_size = 0
    with zf.open(info) as member:
        while True:
            read_size = min(_ZIP_READ_CHUNK_BYTES, max_bytes + 1 - actual_size)
            if read_size <= 0:
                return b"".join(chunks), actual_size, True
            chunk = member.read(read_size)
            if not chunk:
                return b"".join(chunks), actual_size, False
            actual_size += len(chunk)
            if actual_size > max_bytes:
                return b"".join(chunks), actual_size, True
            chunks.append(chunk)


class InstalledSkillReader(LocalDirectoryReader):
    '''通过规范的 skill:// 标识定位已安装技能，并复用本地目录读取器生成快照。'''

    @classmethod
    def from_target(
        cls,
        target: str,
        *,
        storage: Any,
        limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    ) -> InstalledSkillReader:
        '''解析技能类别和相对路径，结合存储后端定位技能目录并构造对应读取器。'''
        category, rel_path = parse_skill_uri(target)
        root = _installed_skill_root(storage, category, rel_path)
        return cls(
            root,
            subject=_subject(
                source="installed",
                category=category,
                name_hint=PurePosixPath(rel_path).name,
                display_ref=f"skill://{category}/{rel_path}",
            ),
            limits=limits,
        )


def parse_skill_uri(target: str) -> tuple[str, str]:
    '''校验 skill://<category>/<path> 标识，并返回经规范化的类别与相对路径。'''
    if not target.startswith("skill://"):
        raise ValueError("Installed skill targets must use skill://<category>/<relative-path>")
    raw = target[len("skill://") :]
    category, sep, rel_path = raw.partition("/")
    if not sep or category not in {"public", "custom", "legacy"}:
        raise ValueError("Skill target must include category: public, custom, or legacy")
    rel_path = normalize_relative_path(rel_path)
    return category, rel_path


def _installed_skill_root(storage: Any, category: str, rel_path: str) -> Path:
    '''按 public、custom 或 legacy 类别使用存储接口解析已安装技能的磁盘位置。'''
    if category == "custom" and hasattr(storage, "get_user_custom_root"):
        return Path(storage.get_user_custom_root()) / rel_path
    if category == "legacy":
        return Path(storage.get_skills_root_path()) / "custom" / rel_path
    return Path(storage.get_skills_root_path()) / category / rel_path
