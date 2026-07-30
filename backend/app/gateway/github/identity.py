'定义 identity 模块提供的职责与可复用接口。\n\nIdentity helpers for GitHub webhook dispatch.\n\nTwo helpers live here:\n\n* :func:`resolve_thread_id` makes the langgraph thread id deterministic\n  from ``(repo, number, agent_name)``. Same PR + same agent → same\n  thread, even across gateway restarts. Different agents on the same PR\n  (e.g. coder + reviewer) deliberately get different thread ids — see\n  the function docstring for the rationale.\n\n* :func:`extract_target` extracts the ``(repo, number)`` pair from a\n  webhook payload, so the dispatcher can route deliveries to the right\n  thread.\n'

from __future__ import annotations

import uuid
from typing import Any

# UUID5 namespace dedicated to GitHub-driven threads. The bytes themselves
# are arbitrary; what matters is that every gateway in the fleet uses the
# *same* namespace so two replicas produce the same thread id for the same
# (repo, number, agent_name) triple. Don't change this without a migration
# plan.
GITHUB_THREAD_NAMESPACE = uuid.UUID("a3f4b2c1-7e8d-4f6a-b9c0-1234567890ab")


def resolve_thread_id(repo: str, issue_or_pr_number: int, agent_name: str) -> str:
    '执行 resolve_thread_id 的明确职责，并返回与调用约定一致的结果。\n\nBuild a deterministic langgraph thread id from a GitHub target + agent.\n\n    The agent name is part of the seed so two agents bound to the same\n    PR/issue (e.g. a coder + a reviewer on ``owner/repo#7``) land on\n    distinct LangGraph threads. Sharing the thread would force\n    ``multitask_strategy="reject"`` to silently drop one run on every\n    dual-mention, and would couple the two agents\' message histories\n    and checkpoints. Each agent now owns its own thread; cross-agent\n    coordination flows through GitHub (PR comments, review threads) —\n    the source of truth humans see anyway.\n\n    Args:\n        repo: ``"owner/name"``.\n        issue_or_pr_number: Issue or PR number (they share the namespace on\n            the GitHub side, so we don\'t need to distinguish here).\n        agent_name: The bound custom agent\'s name. Validated upstream\n            against ``^[A-Za-z0-9-]+$`` (see\n            ``app/gateway/routers/agents.py::AGENT_NAME_PATTERN``) so it\n            is safe to embed verbatim in the UUID5 seed.\n\n    Returns:\n        Stringified UUID5 under :data:`GITHUB_THREAD_NAMESPACE`.\n    '
    if not isinstance(repo, str) or "/" not in repo:
        raise ValueError(f"Expected repo as 'owner/name', got {repo!r}")
    if not isinstance(issue_or_pr_number, int):
        raise ValueError(f"Expected issue_or_pr_number as int, got {type(issue_or_pr_number).__name__}")
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValueError(f"Expected agent_name as non-empty str, got {agent_name!r}")
    return str(uuid.uuid5(GITHUB_THREAD_NAMESPACE, f"{repo}#{issue_or_pr_number}:{agent_name}"))


def extract_target(event: str, payload: dict[str, Any]) -> tuple[str, int] | None:
    '执行 extract_target 的明确职责，并返回与调用约定一致的结果。\n\nBest-effort extraction of (repo, number) from a webhook payload.\n\n    Returns ``None`` when the event has no associated issue/PR number\n    (e.g. ``ping``, ``push``) or when the payload is malformed.\n    '
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
