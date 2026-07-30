"""将线程虚拟路径解析为所属用户线程存储中的实际路径。"""

from pathlib import Path

from fastapi import HTTPException

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id


def resolve_thread_virtual_path(thread_id: str, virtual_path: str, user_id: str | None = None) -> Path:
    """将虚拟路径限定解析到指定用户、指定线程的用户数据存储中。

    未显式提供用户标识时使用当前有效用户；受信任的内部调用方可传入所有者，
    以确保后台任务不会跨越线程和用户的持久化边界。路径穿越或越权目录会被拒绝。
    """
    try:
        return get_paths().resolve_virtual_path(thread_id, virtual_path, user_id=user_id or get_effective_user_id())
    except ValueError as e:
        status = 403 if "traversal" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))
