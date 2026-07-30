"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.channels.message_bus import InboundMessage, MessageBus
from app.gateway.github.dispatcher import fanout_event


def _write_agent(base: Path, user_id: str, name: str, body: dict) -> Path:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    agent_dir = base / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    return agent_dir


@pytest.fixture()
def base_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    from app.gateway.github.registry import _invalidate_cache

    _invalidate_cache()
    return tmp_path


async def _drain(bus: MessageBus) -> list[InboundMessage]:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    out: list[InboundMessage] = []
    while not bus.inbound_queue.empty():
        out.append(await bus.get_inbound())
    return out


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_event_skips_the_owning_agent_only(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer-llm-gateway",
        {
            "name": "reviewer-llm-gateway",
            "github": {
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "llm-gateway-ai",
                            }
                        },
                    }
                ],
            },
        },
    )
    _write_agent(
        base_dir,
        "default",
        "coding-llm-gateway",
        {
            "name": "coding-llm-gateway",
            "github": {
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "coding-llm-gateway-ai",
                            }
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 5, "pull_request": {"url": "..."}},
        "comment": {
            "body": "Following up @coding-llm-gateway-ai please address this.",
            "user": {"login": "llm-gateway-ai[bot]"},
        },
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "llm-gateway-ai[bot]"},
    }
    result = await fanout_event(bus, "issue_comment", "del-self", payload)
    # 说明当前测试分支所验证的真实行为与边界。
    assert "reviewer-llm-gateway" in result["matched_agents"]
    assert "reviewer-llm-gateway" not in result["fired_agents"]
    assert any(s["agent"] == "reviewer-llm-gateway" and s["reason"] == "self_event" for s in result["skipped"])
    # 说明当前测试分支所验证的真实行为与边界。
    assert "coding-llm-gateway" in result["fired_agents"]
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "coding-llm-gateway"


@pytest.mark.asyncio
async def test_third_party_bot_events_are_not_skipped(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer-llm-gateway",
        {
            "name": "reviewer-llm-gateway",
            "github": {
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "llm-gateway-ai",
                            }
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 9, "pull_request": {"url": "..."}},
        "comment": {
            "body": "Hey @llm-gateway-ai, here is my review.",
            "user": {"login": "Copilot"},
        },
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "Copilot", "type": "Bot"},
    }
    result = await fanout_event(bus, "issue_comment", "del-copilot", payload)
    assert "reviewer-llm-gateway" in result["fired_agents"]
    assert result["skipped"] == []
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "reviewer-llm-gateway"


@pytest.mark.asyncio
async def test_agent_name_is_only_a_fallback_when_no_explicit_identity_is_set(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    # 说明当前测试分支所验证的真实行为与边界。
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bot_login": "reviewer-app-bot",
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"pull_request": {"actions": ["opened"]}},
                    }
                ],
            },
        },
    )
    # 说明当前测试分支所验证的真实行为与边界。
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "reviewer"}, "title": "Fix typo", "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "reviewer"},
    }
    result = await fanout_event(bus, "pull_request", "del-collision", payload)
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert result["fired_agents"] == ["reviewer"]
    assert result["skipped"] == []


@pytest.mark.asyncio
async def test_agent_name_fallback_still_works_with_no_explicit_identity(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "solo-bot",
        {
            "name": "solo-bot",
            "github": {
                "bindings": [{"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}}],
            },
        },
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 2, "user": {"login": "solo-bot"}, "title": "x", "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "solo-bot[bot]"},
    }
    result = await fanout_event(bus, "pull_request", "del-solo", payload)
    assert result["fired_agents"] == []
    assert any(s["reason"] == "self_event" for s in result["skipped"])


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_returns_no_target(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    result = await fanout_event(bus, "ping", "del-1", {"zen": "x"})
    assert result["matched_agents"] == []
    assert any(r["reason"] == "no_target" for r in result["skipped"])
    assert await _drain(bus) == []


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_matching_agents_returns_empty(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "zhfeng"}},
        "repository": {"full_name": "a/b"},
    }
    result = await fanout_event(bus, "pull_request", "del-1", payload)
    assert result == {"matched_agents": [], "fired_agents": [], "skipped": []}
    assert await _drain(bus) == []


@pytest.mark.asyncio
async def test_matching_agent_for_different_repo_skips(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "bot",
        {
            "name": "bot",
            "github": {"bindings": [{"repo": "other/repo"}]},
        },
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "zhfeng"}},
        "repository": {"full_name": "a/b"},
    }
    result = await fanout_event(bus, "pull_request", "del-1", payload)
    assert result == {"matched_agents": [], "fired_agents": [], "skipped": []}
    assert await _drain(bus) == []


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_request_opened_fires_and_publishes(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "installation_id": 1234,
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {"pull_request": {"actions": ["opened"]}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 7,
            "title": "Add feature",
            "user": {"login": "zhfeng"},
            "body": "This is my change.",
        },
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "zhfeng"},
    }
    result = await fanout_event(bus, "pull_request", "del-abc", payload)
    assert result["matched_agents"] == ["reviewer"]
    assert result["fired_agents"] == ["reviewer"]
    assert result["skipped"] == []

    messages = await _drain(bus)
    assert len(messages) == 1
    msg = messages[0]
    assert msg.channel_name == "github"
    assert msg.chat_id == "zhfeng/llm-gateway"
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert msg.topic_id == "7:reviewer"
    assert msg.user_id == "zhfeng"
    assert msg.owner_user_id == "default"
    assert "Add feature" in msg.text
    assert msg.metadata["agent_name"] == "reviewer"
    gh = msg.metadata["github"]
    assert gh["repo"] == "zhfeng/llm-gateway"
    assert gh["number"] == 7
    assert gh["installation_id"] == 1234
    assert gh["event"] == "pull_request"
    assert gh["delivery_id"] == "del-abc"
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert gh["recursion_limit"] is None
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert msg.metadata["preferred_thread_id"] == gh["thread_id"]
    assert msg.metadata["preferred_thread_id"]  # 说明当前测试分支所验证的真实行为与边界。


@pytest.mark.asyncio
async def test_per_agent_recursion_limit_flows_through_metadata(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "refactorer",
        {
            "name": "refactorer",
            "github": {
                "installation_id": 1234,
                "recursion_limit": 500,
                "bindings": [
                    {
                        "repo": "owner/big-repo",
                        "triggers": {"pull_request": {"actions": ["opened"]}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "zhfeng"}, "title": "x", "body": ""},
        "repository": {"full_name": "owner/big-repo"},
        "sender": {"login": "zhfeng"},
    }
    await fanout_event(bus, "pull_request", "del-rl", payload)
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["github"]["recursion_limit"] == 500


@pytest.mark.asyncio
async def test_issue_comment_with_mention_fires(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                "bindings": [
                    {
                        "repo": "zhfeng/llm-gateway",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "assistant",
                            }
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 11, "pull_request": {"url": "..."}},
        "comment": {
            "body": "Hey @assistant can you review this?",
            "user": {"login": "zhfeng"},
        },
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "zhfeng"},
    }
    result = await fanout_event(bus, "issue_comment", "del-def", payload)
    assert "assistant" in result["fired_agents"]
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "assistant"


@pytest.mark.asyncio
async def test_issue_comment_without_mention_skipped(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "bot",
        {
            "name": "bot",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"issue_comment": {"require_mention": True}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 2, "pull_request": {"url": "..."}},
        "comment": {"body": "general chat without mention", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "issue_comment", "del-xyz", payload)
    assert result["fired_agents"] == []
    assert len(result["skipped"]) == 1
    assert "mention" in result["skipped"][0]["reason"]
    assert await _drain(bus) == []


@pytest.mark.asyncio
async def test_require_mention_uses_bot_login_when_trigger_omits_mention_login(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "coder",  # 说明当前测试分支所验证的真实行为与边界。
        {
            "name": "coder",
            "github": {
                "bot_login": "deerflow-bot",
                "bindings": [
                    {
                        "repo": "a/b",
                        # 说明当前测试分支所验证的真实行为与边界。
                        # 说明当前测试分支所验证的真实行为与边界。
                        "triggers": {"issue_comment": {"require_mention": True}},
                    }
                ],
            },
        },
    )

    # 说明当前测试分支所验证的真实行为与边界。
    mention_payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @deerflow-bot please look at this", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "issue_comment", "del-bot-mention", mention_payload)
    assert result["fired_agents"] == ["coder"], result
    drained = await _drain(bus)
    assert len(drained) == 1

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    bus_2 = MessageBus()
    dirname_payload = {
        **mention_payload,
        "comment": {"body": "hey @coder look at this", "user": {"login": "alice"}},
    }
    result_2 = await fanout_event(bus_2, "issue_comment", "del-dir-mention", dirname_payload)
    assert result_2["fired_agents"] == [], result_2
    assert len(result_2["skipped"]) == 1
    assert "mention required for @deerflow-bot" in result_2["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_require_mention_falls_back_to_agent_name_when_no_bot_login(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                # 说明当前测试分支所验证的真实行为与边界。
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"issue_comment": {"require_mention": True}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 9, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @assistant please look", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "issue_comment", "del-fallback", payload)
    assert result["fired_agents"] == ["assistant"], result


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operator_default_mention_login_used_when_agent_omits_bot_login(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "coder",
        {
            "name": "coder",
            "github": {
                # 说明当前测试分支所验证的真实行为与边界。
                "bindings": [
                    {"repo": "a/b", "triggers": {"issue_comment": {"require_mention": True}}},
                ],
            },
        },
    )

    # 说明当前测试分支所验证的真实行为与边界。
    fire_payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @deerflow-bot please look", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(
        bus,
        "issue_comment",
        "del-opdef-fire",
        fire_payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result["fired_agents"] == ["coder"], result

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    bus_2 = MessageBus()
    skip_payload = {
        **fire_payload,
        "comment": {"body": "hey @coder look", "user": {"login": "alice"}},
    }
    result_2 = await fanout_event(
        bus_2,
        "issue_comment",
        "del-opdef-skip",
        skip_payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result_2["fired_agents"] == [], result_2
    assert "mention required for @deerflow-bot" in result_2["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_agent_bot_login_outranks_operator_default(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bot_login": "reviewer-bot",  # 说明当前测试分支所验证的真实行为与边界。
                "bindings": [
                    {"repo": "a/b", "triggers": {"issue_comment": {"require_mention": True}}},
                ],
            },
        },
    )

    # 说明当前测试分支所验证的真实行为与边界。
    fire_payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @reviewer-bot please review", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(
        bus,
        "issue_comment",
        "del-perbot",
        fire_payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result["fired_agents"] == ["reviewer"], result

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    bus_2 = MessageBus()
    miss_payload = {
        **fire_payload,
        "comment": {"body": "hey @deerflow-bot review please", "user": {"login": "alice"}},
    }
    result_2 = await fanout_event(
        bus_2,
        "issue_comment",
        "del-perbot-skip",
        miss_payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result_2["fired_agents"] == [], result_2
    assert "mention required for @reviewer-bot" in result_2["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_trigger_mention_login_outranks_operator_default(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "agent-x",
        {
            "name": "agent-x",
            "github": {
                "bot_login": "agent-x-bot",
                "bindings": [
                    {
                        "repo": "a/b",
                        # 说明当前测试分支所验证的真实行为与边界。
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "trigger-handle",
                            }
                        },
                    },
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @trigger-handle please", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(
        bus,
        "issue_comment",
        "del-trigger-override",
        payload,
        operator_default_mention_login="deerflow-bot",
    )
    assert result["fired_agents"] == ["agent-x"], result


@pytest.mark.asyncio
async def test_operator_default_blank_string_treated_as_none(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                "bindings": [
                    {"repo": "a/b", "triggers": {"issue_comment": {"require_mention": True}}},
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @assistant please", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    # 说明当前测试分支所验证的真实行为与边界。
    result = await fanout_event(
        bus,
        "issue_comment",
        "del-blank-opdef",
        payload,
        operator_default_mention_login="   ",
    )
    assert result["fired_agents"] == ["assistant"], result


@pytest.mark.asyncio
async def test_bot_login_whitespace_only_treated_as_none(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                "bot_login": "   ",  # 说明当前测试分支所验证的真实行为与边界。
                "bindings": [
                    {"repo": "a/b", "triggers": {"issue_comment": {"require_mention": True}}},
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @assistant please", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    # 说明当前测试分支所验证的真实行为与边界。
    result = await fanout_event(bus, "issue_comment", "del-blank-bot-login", payload)
    assert result["fired_agents"] == ["assistant"], result


@pytest.mark.asyncio
async def test_trigger_mention_login_whitespace_only_treated_as_none(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "coder",
        {
            "name": "coder",
            "github": {
                "bot_login": "deerflow-bot",  # 说明当前测试分支所验证的真实行为与边界。
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            "issue_comment": {
                                "require_mention": True,
                                "mention_login": "   ",  # 说明当前测试分支所验证的真实行为与边界。
                            }
                        },
                    },
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "hey @deerflow-bot please look", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    # 说明当前测试分支所验证的真实行为与边界。
    result = await fanout_event(bus, "issue_comment", "del-blank-trigger-mention", payload)
    assert result["fired_agents"] == ["coder"], result


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_agents_on_same_repo_event(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    for n in ("alpha", "beta"):
        _write_agent(
            base_dir,
            "default",
            n,
            {
                "name": n,
                "github": {
                    "bindings": [
                        {"repo": "a/b", "triggers": {"pull_request": {}}},
                    ],
                },
            },
        )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "x"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "x"},
    }
    result = await fanout_event(bus, "pull_request", "del-multi", payload)
    assert sorted(result["fired_agents"]) == ["alpha", "beta"]
    messages = await _drain(bus)
    assert sorted(m.metadata["agent_name"] for m in messages) == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_offloads_registry_scan_to_thread(base_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import threading

    main_thread = threading.get_ident()
    seen_threads: list[int] = []

    from app.gateway.github import dispatcher as dispatcher_module

    real = dispatcher_module.build_github_agent_registry

    def _spy() -> dict:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        seen_threads.append(threading.get_ident())
        return real()

    monkeypatch.setattr(dispatcher_module, "build_github_agent_registry", _spy)

    _write_agent(
        base_dir,
        "default",
        "agent-x",
        {"name": "agent-x", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}}]}},
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "user": {"login": "u"}, "title": "x", "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "u"},
    }
    await fanout_event(MessageBus(), "pull_request", "del-thread", payload)

    assert seen_threads, "registry scan was not invoked"
    assert main_thread not in seen_threads, "registry scan must run off the event loop"


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coder_and_reviewer_on_same_pr_get_distinct_threads(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    for n, login in (("coder", "coder-bot"), ("reviewer", "reviewer-bot")):
        _write_agent(
            base_dir,
            "default",
            n,
            {
                "name": n,
                "github": {
                    "bot_login": login,
                    "bindings": [
                        {
                            "repo": "a/b",
                            "triggers": {"pull_request": {"actions": ["opened"]}},
                        }
                    ],
                },
            },
        )
    payload = {
        "action": "opened",
        "pull_request": {"number": 7, "user": {"login": "alice"}, "title": "x", "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "pull_request", "del-split", payload)
    assert sorted(result["fired_agents"]) == ["coder", "reviewer"]

    messages = await _drain(bus)
    assert len(messages) == 2
    by_agent = {m.metadata["agent_name"]: m for m in messages}

    coder, reviewer = by_agent["coder"], by_agent["reviewer"]

    # 说明当前测试分支所验证的真实行为与边界。
    assert coder.metadata["preferred_thread_id"] != reviewer.metadata["preferred_thread_id"]
    # 说明当前测试分支所验证的真实行为与边界。
    assert coder.topic_id != reviewer.topic_id
    assert coder.topic_id == "7:coder"
    assert reviewer.topic_id == "7:reviewer"
    # 说明当前测试分支所验证的真实行为与边界。
    assert coder.metadata["preferred_thread_id"] == coder.metadata["github"]["thread_id"]
    assert reviewer.metadata["preferred_thread_id"] == reviewer.metadata["github"]["thread_id"]


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_id_populates_inbound_dedupe_identity(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {"name": "reviewer", "github": {"installation_id": 1234, "bindings": [{"repo": "zhfeng/llm-gateway", "triggers": {"pull_request": {"actions": ["opened"]}}}]}},
    )
    payload = {
        "action": "opened",
        "pull_request": {"number": 7, "title": "x", "user": {"login": "zhfeng"}, "body": ""},
        "repository": {"full_name": "zhfeng/llm-gateway"},
        "sender": {"login": "zhfeng"},
    }
    await fanout_event(bus, "pull_request", "del-abc", payload)
    (msg,) = await _drain(bus)

    # 说明当前测试分支所验证的真实行为与边界。
    assert msg.workspace_id == "zhfeng/llm-gateway"
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert msg.metadata["message_id"] == "del-abc:default:reviewer"


@pytest.mark.asyncio
async def test_dedupe_identity_stable_across_redelivery_and_distinct_per_agent(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    for n in ("coder", "reviewer"):
        _write_agent(base_dir, "default", n, {"name": n, "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}}]}})
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "title": "x", "user": {"login": "u"}, "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "u"},
    }

    async def _ids(delivery: str) -> dict[str, str]:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        await fanout_event(bus, "pull_request", delivery, payload)
        return {m.metadata["agent_name"]: m.metadata["message_id"] for m in await _drain(bus)}

    first = await _ids("del-1")
    redelivery = await _ids("del-1")
    second = await _ids("del-2")

    # 说明当前测试分支所验证的真实行为与边界。
    assert first["coder"] != first["reviewer"]
    # 说明当前测试分支所验证的真实行为与边界。
    assert redelivery == first
    # 说明当前测试分支所验证的真实行为与边界。
    assert second["coder"] != first["coder"]
    assert second["reviewer"] != first["reviewer"]


@pytest.mark.asyncio
async def test_dedupe_identity_distinguishes_same_agent_name_across_users(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    for user_id in ("alice", "bob"):
        _write_agent(
            base_dir,
            user_id,
            "reviewer",
            {
                "name": "reviewer",
                "github": {
                    "bindings": [
                        {"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}},
                    ],
                },
            },
        )
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "title": "x", "user": {"login": "u"}, "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "u"},
    }
    result = await fanout_event(bus, "pull_request", "del-cross-user", payload)
    assert result["fired_agents"] == ["reviewer", "reviewer"]

    messages = await _drain(bus)
    assert len(messages) == 2
    by_owner = {m.owner_user_id: m for m in messages}
    assert set(by_owner) == {"alice", "bob"}

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert by_owner["alice"].metadata["message_id"] != by_owner["bob"].metadata["message_id"]

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    from app.channels.manager import ChannelManager
    from app.channels.store import ChannelStore

    manager = ChannelManager(bus=MessageBus(), store=ChannelStore(path=base_dir / "dedupe-store.json"))
    assert manager._is_duplicate_inbound(by_owner["alice"]) is False
    assert manager._is_duplicate_inbound(by_owner["bob"]) is False


@pytest.mark.asyncio
async def test_missing_delivery_header_leaves_dedupe_open(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(base_dir, "default", "reviewer", {"name": "reviewer", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {"actions": ["opened"]}}}]}})
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "title": "x", "user": {"login": "u"}, "body": ""},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "u"},
    }
    await fanout_event(bus, "pull_request", "", payload)
    (msg,) = await _drain(bus)
    assert msg.metadata["message_id"] is None


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
#
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
#
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_comment_companion_to_review_is_suppressed(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            # 说明当前测试分支所验证的真实行为与边界。
                            # 说明当前测试分支所验证的真实行为与边界。
                            # 说明当前测试分支所验证的真实行为与边界。
                            "pull_request_review": {},
                            "pull_request_review_comment": {"require_mention": False},
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "nit: consider renaming this variable.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-storm-1", payload)
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert result["matched_agents"] == ["reviewer"], result
    assert result["fired_agents"] == [], result
    assert any(s["agent"] == "reviewer" and s["reason"] == "redundant_review_comment" for s in result["skipped"]), result
    assert await _drain(bus) == []


@pytest.mark.asyncio
async def test_review_comment_only_binding_not_suppressed(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        # 说明当前测试分支所验证的真实行为与边界。
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "nit: consider renaming this variable.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-storm-2", payload)
    assert result["matched_agents"] == ["reviewer"], result
    assert result["fired_agents"] == ["reviewer"], result
    assert result["skipped"] == [], result
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "reviewer"


@pytest.mark.asyncio
async def test_review_comment_not_suppressed_when_review_trigger_is_on_different_repo(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "multi-repo-bot",
        {
            "name": "multi-repo-bot",
            "github": {
                "bindings": [
                    {
                        "repo": "owner/x",
                        "triggers": {"pull_request_review": {}},
                    },
                    {
                        "repo": "owner/y",
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    },
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 3},
        "comment": {
            "body": "nit on repo Y.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 42,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "owner/y"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-storm-3", payload)
    assert result["fired_agents"] == ["multi-repo-bot"], result
    assert result["skipped"] == [], result


@pytest.mark.asyncio
async def test_review_comment_reply_within_thread_still_fires(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "Good catch, fixed in the latest push.",
            "user": {"login": "alice"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": 555002,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-reply-1", payload)
    assert result["fired_agents"] == ["reviewer"], result
    assert result["skipped"] == []
    messages = await _drain(bus)
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_review_comment_without_review_id_still_fires(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "Standalone inline comment, no parent review.",
            "user": {"login": "alice"},
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-noreviewid-1", payload)
    assert result["fired_agents"] == ["reviewer"], result
    assert result["skipped"] == []


@pytest.mark.asyncio
async def test_issue_comment_unaffected_by_review_comment_filter(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "assistant",
        {
            "name": "assistant",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"issue_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "issue": {"number": 3, "pull_request": {"url": "..."}},
        "comment": {"body": "just a regular comment", "user": {"login": "alice"}},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "issue_comment", "del-issue-1", payload)
    assert result["fired_agents"] == ["assistant"], result
    assert result["skipped"] == []


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
#
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_comment_not_suppressed_when_review_trigger_requires_mention(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            # 说明当前测试分支所验证的真实行为与边界。
                            # 说明当前测试分支所验证的真实行为与边界。
                            # 说明当前测试分支所验证的真实行为与边界。
                            "pull_request_review": {"require_mention": True},
                            "pull_request_review_comment": {"require_mention": True},
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            # 说明当前测试分支所验证的真实行为与边界。
            # 说明当前测试分支所验证的真实行为与边界。
            "body": "@reviewer this needs another look before merging.",
            "user": {"login": "alice"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "alice"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-req-mention-1", payload)
    assert result["fired_agents"] == ["reviewer"], result
    assert result["skipped"] == [], result
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "reviewer"
    assert "@reviewer this needs another look" in messages[0].text


@pytest.mark.asyncio
async def test_review_comment_gate_is_independent_per_agent_in_same_call(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "coder",
        {
            "name": "coder",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            "pull_request_review": {},
                            "pull_request_review_comment": {"require_mention": False},
                        },
                    }
                ],
            },
        },
    )
    _write_agent(
        base_dir,
        "default",
        "notifier",
        {
            "name": "notifier",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {"pull_request_review_comment": {"require_mention": False}},
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "nit: consider renaming this variable.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-multi-agent-1", payload)
    assert set(result["matched_agents"]) == {"coder", "notifier"}, result
    assert result["fired_agents"] == ["notifier"], result
    assert result["skipped"] == [{"agent": "coder", "reason": "redundant_review_comment"}], result
    messages = await _drain(bus)
    assert len(messages) == 1
    assert messages[0].metadata["agent_name"] == "notifier"


@pytest.mark.asyncio
async def test_review_comment_redundant_skip_prefers_own_trigger_reason_when_it_also_fails(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()
    _write_agent(
        base_dir,
        "default",
        "reviewer",
        {
            "name": "reviewer",
            "github": {
                "bindings": [
                    {
                        "repo": "a/b",
                        "triggers": {
                            # 说明当前测试分支所验证的真实行为与边界。
                            "pull_request_review": {},
                            # 说明当前测试分支所验证的真实行为与边界。
                            # 说明当前测试分支所验证的真实行为与边界。
                            "pull_request_review_comment": {"require_mention": True},
                        },
                    }
                ],
            },
        },
    )
    payload = {
        "action": "created",
        "pull_request": {"number": 7},
        "comment": {
            "body": "nit: consider renaming this variable.",
            "user": {"login": "coderabbitai[bot]"},
            "pull_request_review_id": 999001,
            "in_reply_to_id": None,
        },
        "repository": {"full_name": "a/b"},
        "sender": {"login": "coderabbitai[bot]"},
    }
    result = await fanout_event(bus, "pull_request_review_comment", "del-precedence-1", payload)
    assert result["fired_agents"] == [], result
    assert len(result["skipped"]) == 1
    reason = result["skipped"][0]["reason"]
    assert reason != "redundant_review_comment", result
    assert "mention" in reason, result
