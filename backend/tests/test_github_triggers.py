"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import pytest

from app.gateway.github.triggers import (
    DEFAULT_TRIGGERS,
    _resolved_trigger,
    event_should_fire,
)
from deerflow.config.agents_config import GitHubTriggerConfig

BOT = "coding-llm-gateway"


def _pr_payload(action: str = "opened", author: str = "zhfeng") -> dict:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    return {
        "action": action,
        "pull_request": {"number": 7, "user": {"login": author}},
        "repository": {"full_name": "a/b"},
    }


def _comment_payload(body: str, author: str = "zhfeng") -> dict:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    return {
        "action": "created",
        "issue": {"number": 11},
        "comment": {"body": body, "user": {"login": author}},
        "repository": {"full_name": "a/b"},
    }


def _resolve(event: str, override: GitHubTriggerConfig | None = None) -> GitHubTriggerConfig:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    override = override if override is not None else GitHubTriggerConfig()
    resolved = _resolved_trigger(event, {event: override})
    assert resolved is not None  # 说明当前测试分支所验证的真实行为与边界。
    return resolved


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------
#
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。


def test_default_pull_request_opened_fires() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fire, reason = event_should_fire("pull_request", _pr_payload("opened"), _resolve("pull_request"), BOT)
    assert fire is True
    assert "opened" in reason


def test_default_pull_request_synchronize_does_not_fire() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fire, reason = event_should_fire("pull_request", _pr_payload("synchronize"), _resolve("pull_request"), BOT)
    assert fire is False
    assert "synchronize" in reason


def test_default_issue_comment_without_mention_does_not_fire() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fire, reason = event_should_fire("issue_comment", _comment_payload("just a thought"), _resolve("issue_comment"), BOT)
    assert fire is False
    assert "mention" in reason.lower()


def test_default_issue_comment_with_mention_fires() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fire, _ = event_should_fire("issue_comment", _comment_payload(f"hey @{BOT} please look"), _resolve("issue_comment"), BOT)
    assert fire is True


def test_default_issue_comment_mention_case_insensitive() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fire, _ = event_should_fire("issue_comment", _comment_payload(f"hey @{BOT.upper()} look"), _resolve("issue_comment"), BOT)
    assert fire is True


def test_event_not_in_binding_is_disabled_at_registry() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert _resolved_trigger("pull_request", {}) is None


def test_default_ping_is_disabled_even_when_opted_in() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert DEFAULT_TRIGGERS["ping"] is None


def test_default_issues_is_disabled_unless_listed_at_registry() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert _resolved_trigger("issues", {}) is None


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_action_whitelist_overrides_default() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("pull_request", GitHubTriggerConfig(actions=["opened", "reopened"]))
    fire, _ = event_should_fire("pull_request", _pr_payload("reopened"), trigger, BOT)
    assert fire is True


def test_empty_actions_list_blocks_all() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("pull_request", GitHubTriggerConfig(actions=[]))
    fire, _ = event_should_fire("pull_request", _pr_payload("opened"), trigger, BOT)
    assert fire is False


def test_actions_none_allows_any_action() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("pull_request", GitHubTriggerConfig(actions=None))
    fire, _ = event_should_fire("pull_request", _pr_payload("labeled"), trigger, BOT)
    assert fire is True


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_allow_authors_bypasses_mention_requirement() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, allow_authors=["zhfeng"]))
    fire, reason = event_should_fire(
        "issue_comment",
        _comment_payload("no handle here", author="zhfeng"),
        trigger,
        BOT,
    )
    assert fire is True
    assert "zhfeng" in reason


def test_allow_authors_does_not_help_other_users() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, allow_authors=["alice"]))
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload("no handle", author="bob"),
        trigger,
        BOT,
    )
    assert fire is False


@pytest.mark.parametrize(
    ("allow_authors", "author"),
    [
        (["Alice"], "alice"),  # 说明当前测试分支所验证的真实行为与边界。
        (["alice"], "Alice"),  # 说明当前测试分支所验证的真实行为与边界。
        (["ALICE"], "alice"),  # 说明当前测试分支所验证的真实行为与边界。
        (["Alice"], "Alice"),  # 说明当前测试分支所验证的真实行为与边界。
    ],
)
def test_allow_authors_match_is_case_insensitive(allow_authors: list[str], author: str) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve(
        "issue_comment",
        GitHubTriggerConfig(require_mention=True, allow_authors=allow_authors),
    )
    fire, reason = event_should_fire(
        "issue_comment",
        _comment_payload("no handle here", author=author),
        trigger,
        BOT,
    )
    assert fire is True
    assert "allow_authors" in reason


def test_allow_authors_case_insensitive_still_rejects_other_users() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve(
        "issue_comment",
        GitHubTriggerConfig(require_mention=True, allow_authors=["Alice"]),
    )
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload("no handle", author="bob"),
        trigger,
        BOT,
    )
    assert fire is False


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_mention_login_override() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login="other-bot"))
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload("hi @other-bot"),
        trigger,
        BOT,
    )
    assert fire is True


def test_mention_login_override_default_login_does_not_match() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login="other-bot"))
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload(f"hi @{BOT}"),
        trigger,
        BOT,
    )
    assert fire is False


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_enabling_issues_via_override() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issues", GitHubTriggerConfig(actions=["opened"]))
    fire, _ = event_should_fire(
        "issues",
        {
            "action": "opened",
            "issue": {"number": 1, "user": {"login": "x"}},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is True


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_issues_require_mention_fires_when_body_mentions_bot() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issues", GitHubTriggerConfig(actions=["opened"], require_mention=True, mention_login=BOT))
    fire, reason = event_should_fire(
        "issues",
        {
            "action": "opened",
            "issue": {"number": 1, "user": {"login": "alice"}, "body": f"Hey @{BOT} please fix this"},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is True
    assert "mention" not in reason  # 说明当前测试分支所验证的真实行为与边界。


def test_issues_require_mention_skips_without_mention() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issues", GitHubTriggerConfig(actions=["opened"], require_mention=True, mention_login=BOT))
    fire, reason = event_should_fire(
        "issues",
        {
            "action": "opened",
            "issue": {"number": 1, "user": {"login": "alice"}, "body": "just a normal bug report"},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is False
    assert "mention required" in reason


def test_issues_allow_authors_bypasses_mention() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issues", GitHubTriggerConfig(actions=["opened"], require_mention=True, mention_login=BOT, allow_authors=["zhfeng"]))
    fire, reason = event_should_fire(
        "issues",
        {
            "action": "opened",
            "issue": {"number": 1, "user": {"login": "zhfeng"}, "body": "no mention here"},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is True
    assert "allow_authors" in reason


def test_pull_request_require_mention_scans_pr_body() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("pull_request", GitHubTriggerConfig(actions=["opened"], require_mention=True, mention_login=BOT))
    fire, _ = event_should_fire(
        "pull_request",
        {
            "action": "opened",
            "pull_request": {"number": 3, "user": {"login": "bob"}, "body": f"@{BOT} can you finish this?"},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is True


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_pull_request_review_require_mention_fires_on_review_body_mention() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("pull_request_review", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    fire, reason = event_should_fire(
        "pull_request_review",
        {
            "action": "submitted",
            "pull_request": {"number": 4},
            "review": {"user": {"login": "alice"}, "body": f"@{BOT} please look again", "state": "commented"},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is True
    assert "mention" not in reason


def test_pull_request_review_require_mention_skips_without_mention() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("pull_request_review", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    fire, reason = event_should_fire(
        "pull_request_review",
        {
            "action": "submitted",
            "pull_request": {"number": 5},
            "review": {"user": {"login": "alice"}, "body": "looks good", "state": "approved"},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is False
    assert "mention required" in reason


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_mention_prefix_does_not_match_longer_login() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login="deerflow"))
    fire, reason = event_should_fire(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 1, "user": {"login": "alice"}},
            "comment": {"body": "Hey @deerflow-bot please review", "user": {"login": "alice"}},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        "deerflow",
    )
    assert fire is False
    assert "mention required" in reason


def test_mention_inside_email_does_not_match() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    fire, _ = event_should_fire(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 1, "user": {"login": "alice"}},
            "comment": {"body": f"contact noreply@{BOT}.example to retrigger", "user": {"login": "alice"}},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is False


def test_mention_at_start_of_body_matches() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    fire, _ = event_should_fire(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 1, "user": {"login": "alice"}},
            "comment": {"body": f"@{BOT} ping", "user": {"login": "alice"}},
            "repository": {"full_name": "a/b"},
        },
        trigger,
        BOT,
    )
    assert fire is True


def test_mention_followed_by_punctuation_matches() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    for body in (f"hey @{BOT}, please look", f"asked @{BOT}.", f"thanks @{BOT}!"):
        fire, _ = event_should_fire(
            "issue_comment",
            {
                "action": "created",
                "issue": {"number": 1, "user": {"login": "alice"}},
                "comment": {"body": body, "user": {"login": "alice"}},
                "repository": {"full_name": "a/b"},
            },
            trigger,
            BOT,
        )
        assert fire is True, f"expected mention to match in: {body!r}"
