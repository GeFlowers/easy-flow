"""根据 agent 绑定配置筛选 GitHub webhook 事件，并返回筛选原因。"""

from __future__ import annotations

import re
from typing import Any

from deerflow.config.agents_config import GitHubTriggerConfig

# Per-event field-level defaults. These are merged into a binding's
# override when the event IS listed in the binding's ``triggers:``. They
# no longer enable the event by themselves — the binding must list the
# event for the agent to register for it.
#
# ``None`` means "no per-event defaults; use whatever the binding set
# (or the model's own field defaults)".
DEFAULT_TRIGGERS: dict[str, GitHubTriggerConfig | None] = {
    "ping": None,
    "issues": None,
    "pull_request_review": None,
    "pull_request": GitHubTriggerConfig(actions=["opened"]),
    "issue_comment": GitHubTriggerConfig(require_mention=True),
    "pull_request_review_comment": GitHubTriggerConfig(require_mention=True),
}


def _action(payload: dict[str, Any]) -> str | None:
    """从事件负载中提取字符串类型的动作值。"""
    action = payload.get("action")
    return action if isinstance(action, str) else None


def _comment_body(event: str, payload: dict[str, Any]) -> str:
    """按事件类型读取需要检查 @提及的评论、issue、PR 或 review 正文。"""
    if event in ("issue_comment", "pull_request_review_comment"):
        body = (payload.get("comment") or {}).get("body")
        return body if isinstance(body, str) else ""
    if event == "issues":
        body = (payload.get("issue") or {}).get("body")
        return body if isinstance(body, str) else ""
    if event == "pull_request":
        body = (payload.get("pull_request") or {}).get("body")
        return body if isinstance(body, str) else ""
    if event == "pull_request_review":
        body = (payload.get("review") or {}).get("body")
        return body if isinstance(body, str) else ""
    return ""


def _author_login(event: str, payload: dict[str, Any]) -> str | None:
    """从事件负载对应的主体字段读取触发者登录名，供作者白名单判断。"""
    if event in ("issue_comment", "pull_request_review_comment"):
        login = (payload.get("comment") or {}).get("user", {}).get("login")
    elif event == "pull_request":
        login = (payload.get("pull_request") or {}).get("user", {}).get("login")
    elif event == "pull_request_review":
        login = (payload.get("review") or {}).get("user", {}).get("login")
    elif event == "issues":
        login = (payload.get("issue") or {}).get("user", {}).get("login")
    else:
        login = (payload.get("sender") or {}).get("login")
    return login if isinstance(login, str) else None


def _resolved_trigger(
    event: str,
    binding_triggers: dict[str, GitHubTriggerConfig],
) -> GitHubTriggerConfig | None:
    """合并绑定显式配置与事件默认值；未在绑定中列出的事件保持禁用。"""
    override = binding_triggers.get(event)
    if override is None:
        return None

    default = DEFAULT_TRIGGERS.get(event)
    if default is None:
        return override

    # 保留绑定显式设置的字段，其余字段继承事件默认值。
    explicit = override.model_dump(exclude_unset=True)
    merged = default.model_copy(update=explicit)
    return merged


def _mentions(body: str, login: str) -> bool:
    """按 GitHub 登录名边界进行大小写不敏感的 @提及匹配，避免匹配相似账号或邮箱地址。"""
    pattern = rf"(?:^|[^A-Za-z0-9-])@{re.escape(login)}(?![A-Za-z0-9-])"
    return re.search(pattern, body, flags=re.IGNORECASE) is not None


def event_should_fire(
    event: str,
    payload: dict[str, Any],
    trigger: GitHubTriggerConfig,
    default_mention_login: str,
) -> tuple[bool, str]:
    """依次应用动作白名单、作者白名单和提及要求，返回是否触发及便于日志排查的原因。"""
    # 先按事件动作过滤，例如只响应新建的 PR。
    if trigger.actions is not None:
        action = _action(payload)
        if action not in trigger.actions:
            return False, f"action={action!r} not in {trigger.actions}"

    # 作者白名单可绕过提及要求，登录名按大小写不敏感方式比较。
    if trigger.allow_authors:
        author = _author_login(event, payload)
        if author and author.lower() in {a.lower() for a in trigger.allow_authors}:
            return True, f"allow_authors:{author}"

    if trigger.require_mention:
        # ``trigger.mention_login`` is normalized (whitespace-only -> None)
        # by ``GitHubTriggerConfig``'s field validator, so this ``or`` falls
        # through a misconfigured ``mention_login: "   "`` to
        # ``default_mention_login`` instead of gating on a literal
        # whitespace string that no real ``@mention`` could ever match.
        login = trigger.mention_login or default_mention_login
        body = _comment_body(event, payload)
        # Boundary-aware @-mention match: ``@deerflow`` must NOT match
        # ``@deerflow-bot`` (a distinct, legitimate GitHub login). See
        # :func:`_mentions` for the full rationale.
        if not login or not _mentions(body, login):
            return False, f"mention required for @{login}"

    # 所有启用的筛选条件均通过。
    action = _action(payload)
    return True, f"action={action}" if action else "ok"
