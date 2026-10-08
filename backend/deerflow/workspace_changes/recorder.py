'''在运行前后扫描线程工作区，并把安全过滤后的变化写入运行事件存储。'''

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from deerflow.config import get_paths

from .diff import compare_snapshots, get_changed_paths
from .scanner import scan_workspace_roots
from .types import (
    WORKSPACE_CHANGES_EVENT_TYPE,
    WORKSPACE_CHANGES_METADATA_KEY,
    WorkspaceChangeLimits,
    WorkspaceRoot,
    WorkspaceSnapshot,
)

logger = logging.getLogger(__name__)


def build_thread_workspace_roots(thread_id: str, *, user_id: str | None = None) -> list[WorkspaceRoot]:
    '''为线程工作目录和生成产物建立待扫描根目录及虚拟路径映射。'''
    paths = get_paths()
    return [
        WorkspaceRoot(
            name="workspace",
            host_path=paths.sandbox_work_dir(thread_id, user_id=user_id),
            virtual_prefix="/mnt/user-data/workspace",
        ),
        WorkspaceRoot(
            name="outputs",
            host_path=paths.sandbox_outputs_dir(thread_id, user_id=user_id),
            virtual_prefix="/mnt/user-data/outputs",
        ),
    ]


async def capture_workspace_snapshot(
    thread_id: str,
    *,
    user_id: str | None = None,
    limits: WorkspaceChangeLimits | None = None,
    include_text: bool = True,
) -> WorkspaceSnapshot:
    '''在线程任务执行期间异步扫描工作区，并为后续比较准备文本快照。'''
    roots = build_thread_workspace_roots(thread_id, user_id=user_id)
    text_cache_dir = Path(tempfile.mkdtemp(prefix="deerflow-workspace-changes-")) if include_text else None
    try:
        return await asyncio.to_thread(
            scan_workspace_roots,
            roots,
            limits=limits,
            include_text=include_text,
            text_cache_dir=text_cache_dir,
        )
    except Exception:
        if text_cache_dir is not None:
            shutil.rmtree(text_cache_dir, ignore_errors=True)
        raise


async def record_workspace_changes(
    event_store: Any,
    thread_id: str,
    run_id: str,
    before: WorkspaceSnapshot,
    *,
    user_id: str | None = None,
    limits: WorkspaceChangeLimits | None = None,
) -> dict | None:
    '''扫描执行后的变化，只读取发生变化的文本，并将摘要事件写入数据库。'''
    try:
        roots = build_thread_workspace_roots(thread_id, user_id=user_id)
        after_metadata = await asyncio.to_thread(
            scan_workspace_roots,
            roots,
            limits=limits,
            include_text=False,
        )
        changed_paths = get_changed_paths(before, after_metadata)
        after = await asyncio.to_thread(
            scan_workspace_roots,
            roots,
            limits=limits,
            include_text=True,
            text_paths=changed_paths,
        )
        result = compare_snapshots(before, after, limits=limits)
        if not result.has_changes():
            return None

        payload = result.to_dict()
        summary = result.summary
        changed_file_count = summary.created + summary.modified + summary.deleted
        content = f"{changed_file_count} file{'s' if changed_file_count != 1 else ''} changed +{summary.additions} -{summary.deletions}"
        return await event_store.put(
            thread_id=thread_id,
            run_id=run_id,
            event_type=WORKSPACE_CHANGES_EVENT_TYPE,
            category="workspace",
            content=content,
            metadata={WORKSPACE_CHANGES_METADATA_KEY: payload},
        )
    finally:
        _cleanup_snapshot_text_cache(before)


def _cleanup_snapshot_text_cache(snapshot: WorkspaceSnapshot) -> None:
    '''删除快照使用的临时文本缓存，避免运行结束后遗留文件。'''
    if snapshot.text_cache_dir:
        shutil.rmtree(snapshot.text_cache_dir, ignore_errors=True)
