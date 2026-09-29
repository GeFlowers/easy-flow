"""提供 GitHub webhook 的线程标识生成及仓库议题目标提取函数。"""

from __future__ import annotations

import uuid
from typing import Any

# GitHub 线程专用的 UUID5 命名空间。所有网关副本必须保持一致；更改前需规划线程标识迁移。
GITHUB_THREAD_NAMESPACE = uuid.UUID("a3f4b2c1-7e8d-4f6a-b9c0-1234567890ab")


def resolve_thread_id(repo: str, issue_or_pr_number: int, agent_name: str) -> str:
    """根据仓库、议题编号和 agent 名称生成稳定线程 ID，不同 agent 各自拥有独立对话历史。

    Args:
        repo: ``owner/name`` 格式的仓库全名。
        issue_or_pr_number: GitHub issue 或 pull request 编号。
        agent_name: 绑定到该仓库事件的自定义 agent 名称。

    Returns:
        基于 GitHub 专用命名空间生成的 UUID 字符串。
    """
    if not isinstance(repo, str) or "/" not in repo:
        raise ValueError(f"Expected repo as 'owner/name', got {repo!r}")
    if not isinstance(issue_or_pr_number, int):
        raise ValueError(f"Expected issue_or_pr_number as int, got {type(issue_or_pr_number).__name__}")
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValueError(f"Expected agent_name as non-empty str, got {agent_name!r}")
    return str(uuid.uuid5(GITHUB_THREAD_NAMESPACE, f"{repo}#{issue_or_pr_number}:{agent_name}"))


def extract_target(event: str, payload: dict[str, Any]) -> tuple[str, int] | None:
    """从支持的 webhook 负载中提取仓库名与 issue/PR 编号；事件不相关或数据格式错误时返回 ``None``。"""
    repo = (payload.get("repository") or {}).get("full_name")
    if not isinstance(repo, str):
        return None

    number: int | None = None
    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        number = pr.get("number") or payload.get("number")
    elif event == "pull_request_review":
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
    elif event == "pull_request_review_comment":
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
    elif event == "issue_comment":
        number = (payload.get("issue") or {}).get("number")
    elif event == "issues":
        number = (payload.get("issue") or {}).get("number")
    else:
        return None

    if not isinstance(number, int):
        return None
    return repo, number
