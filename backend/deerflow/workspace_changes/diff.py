'''比较工作区前后快照，统计文件变化并在安全限制内生成统一差异。'''

from __future__ import annotations

import difflib

from .types import (
    DiffUnavailableReason,
    FileSnapshot,
    WorkspaceChangeLimits,
    WorkspaceChangeResult,
    WorkspaceChangeStatus,
    WorkspaceChangeSummary,
    WorkspaceFileChange,
    WorkspaceSnapshot,
)


def compare_snapshots(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
    *,
    limits: WorkspaceChangeLimits | None = None,
) -> WorkspaceChangeResult:
    '''合并两次快照的路径集合，生成受文件数和字节数限制的变化结果。'''
    resolved_limits = limits or WorkspaceChangeLimits()
    all_paths = sorted(set(before.files) | set(after.files))
    changes: list[WorkspaceFileChange] = []
    created = modified = deleted = additions = deletions = 0
    total_diff_bytes = 0
    truncated = before.truncated or after.truncated

    for path in all_paths:
        before_file = before.files.get(path)
        after_file = after.files.get(path)
        if before_file and after_file and _same_file(before_file, after_file):
            continue

        status = _status(before_file, after_file)
        if status == "created":
            created += 1
        elif status == "modified":
            modified += 1
        else:
            deleted += 1

        diff, line_additions, line_deletions, diff_truncated, reason = _build_diff(
            path,
            before_file,
            after_file,
            remaining_bytes=max(0, resolved_limits.max_total_diff_bytes - total_diff_bytes),
        )
        if diff:
            total_diff_bytes += len(diff.encode("utf-8"))
        if diff_truncated or reason in {"large", "truncated"}:
            truncated = True
        additions += line_additions
        deletions += line_deletions

        if len(changes) < resolved_limits.max_files:
            sample = after_file or before_file
            assert sample is not None
            changes.append(
                WorkspaceFileChange(
                    path=path,
                    root=sample.root,
                    status=status,
                    binary=bool((after_file or before_file).binary if (after_file or before_file) else False),
                    sensitive=bool((after_file or before_file).sensitive if (after_file or before_file) else False),
                    size_before=before_file.size if before_file else None,
                    size_after=after_file.size if after_file else None,
                    sha256_before=before_file.sha256 if before_file else None,
                    sha256_after=after_file.sha256 if after_file else None,
                    diff=diff,
                    diff_truncated=diff_truncated,
                    diff_unavailable_reason=reason,
                    additions=line_additions,
                    deletions=line_deletions,
                )
            )
        else:
            truncated = True

    return WorkspaceChangeResult(
        summary=WorkspaceChangeSummary(
            created=created,
            modified=modified,
            deleted=deleted,
            additions=additions,
            deletions=deletions,
            truncated=truncated,
        ),
        files=changes,
        limits=resolved_limits,
    )


def get_changed_paths(before: WorkspaceSnapshot, after: WorkspaceSnapshot) -> set[str]:
    '''仅返回前后快照中内容或元数据发生变化的路径集合。'''
    changed: set[str] = set()
    for path in set(before.files) | set(after.files):
        before_file = before.files.get(path)
        after_file = after.files.get(path)
        if before_file and after_file and _same_file(before_file, after_file):
            continue
        changed.add(path)
    return changed


def _status(
    before_file: FileSnapshot | None,
    after_file: FileSnapshot | None,
) -> WorkspaceChangeStatus:
    '''根据文件仅出现在新旧快照哪一侧判定新增、删除或修改。'''
    if before_file is None:
        return "created"
    if after_file is None:
        return "deleted"
    return "modified"


def _same_file(before_file: FileSnapshot, after_file: FileSnapshot) -> bool:
    '''优先比较内容摘要；缺少摘要时以大小和修改时间判断文件是否相同。'''
    if before_file.sha256 is not None and after_file.sha256 is not None:
        return before_file.sha256 == after_file.sha256
    return before_file.size == after_file.size and before_file.mtime_ns == after_file.mtime_ns


def _build_diff(
    path: str,
    before_file: FileSnapshot | None,
    after_file: FileSnapshot | None,
    *,
    remaining_bytes: int,
) -> tuple[str, int, int, bool, DiffUnavailableReason | None]:
    '''检查内容是否适合比较，读取快照文本并生成统一差异及增删行数。'''
    reason = _diff_unavailable_reason(before_file, after_file)
    if reason is not None:
        return "", 0, 0, False, reason

    before_text = _snapshot_text(before_file) if before_file else ""
    after_text = _snapshot_text(after_file) if after_file else ""

    if before_file is not None and before_text is None:
        return "", 0, 0, False, None
    if after_file is not None and after_text is None:
        return "", 0, 0, False, None

    lines = list(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile=f"a{path}",
            tofile=f"b{path}",
            lineterm="",
        )
    )
    diff = "\n".join(lines)
    additions, deletions = _count_diff_lines(lines)
    if len(diff.encode("utf-8")) > remaining_bytes:
        return "", additions, deletions, True, "truncated"
    return diff, additions, deletions, False, None


def _diff_unavailable_reason(
    before_file: FileSnapshot | None,
    after_file: FileSnapshot | None,
) -> DiffUnavailableReason | None:
    '''按敏感、二进制、过大优先级确定不能展示差异的原因。'''
    files = [file for file in (before_file, after_file) if file is not None]
    for preferred in ("sensitive", "binary", "large"):
        if any(file.content_unavailable_reason == preferred for file in files):
            return preferred  # type: ignore[return-value]
    return None


def _snapshot_text(file: FileSnapshot | None) -> str | None:
    '''从快照内存内容或临时缓存文件读取文本；缓存失效时返回空值。'''
    if file is None:
        return ""
    if file.text is not None:
        return file.text
    if file.text_path:
        try:
            with open(file.text_path, encoding="utf-8") as cached:
                return cached.read()
        except OSError:
            return None
    return None


def _count_diff_lines(lines: list[str]) -> tuple[int, int]:
    '''统计统一差异中的新增和删除行，排除文件头部标记。'''
    additions = 0
    deletions = 0
    for line in lines:
        # unified_diff 的 +++/--- 文件头不是内容变化行，必须排除在统计之外。
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions
