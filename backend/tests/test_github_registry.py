"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.gateway.github.registry import (
    _invalidate_cache,
    build_github_agent_registry,
    lookup_agents,
)


def _write_agent(base: Path, user_id: str, name: str, body: dict) -> Path:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    agent_dir = base / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    return agent_dir


def _write_legacy_agent(base: Path, name: str, body: dict) -> Path:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    agent_dir = base / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    return agent_dir


@pytest.fixture()
def base_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    _invalidate_cache()
    return tmp_path


def test_registry_empty_when_no_agents(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    registry = build_github_agent_registry()
    assert registry == {}


def test_registry_skips_agents_without_github_block(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(base_dir, "default", "plain", {"name": "plain"})
    registry = build_github_agent_registry()
    assert registry == {}


def test_registry_indexes_by_repo_and_event(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
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
                        "triggers": {"pull_request": {"actions": ["opened"]}},
                    }
                ],
            },
        },
    )
    registry = build_github_agent_registry()
    matched = lookup_agents(registry, "zhfeng/llm-gateway", "pull_request")
    assert len(matched) == 1
    assert matched[0].agent.name == "coding-llm-gateway"
    assert matched[0].user_id == "default"
    assert matched[0].agent.github.installation_id is None  # 说明当前测试分支所验证的真实行为与边界。


def test_registry_does_not_register_events_the_binding_omits(base_dir: Path) -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "silent",
        {
            "name": "silent",
            "github": {"bindings": [{"repo": "a/b"}]},
        },
    )
    registry = build_github_agent_registry()
    for event in (
        "pull_request",
        "issue_comment",
        "pull_request_review_comment",
        "pull_request_review",
        "issues",
        "ping",
    ):
        assert lookup_agents(registry, "a/b", event) == [], event


def test_registry_indexes_only_explicitly_listed_events(base_dir: Path) -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "pr-only",
        {
            "name": "pr-only",
            "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]},
        },
    )
    registry = build_github_agent_registry()
    assert len(lookup_agents(registry, "a/b", "pull_request")) == 1
    assert lookup_agents(registry, "a/b", "issue_comment") == []
    assert lookup_agents(registry, "a/b", "pull_request_review_comment") == []


def test_registry_picks_up_event_only_via_explicit_trigger_override(base_dir: Path) -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "issue-bot",
        {
            "name": "issue-bot",
            "github": {"bindings": [{"repo": "a/b", "triggers": {"issues": {}}}]},
        },
    )
    registry = build_github_agent_registry()
    matched = lookup_agents(registry, "a/b", "issues")
    assert len(matched) == 1
    assert matched[0].agent.name == "issue-bot"


def test_registry_supports_multiple_agents_on_same_repo_event(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
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
    registry = build_github_agent_registry()
    matched = lookup_agents(registry, "a/b", "pull_request")
    names = sorted(m.agent.name for m in matched)
    assert names == ["alpha", "beta"]


def test_registry_supports_one_agent_on_multiple_repos(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "multi",
        {
            "name": "multi",
            "github": {
                "bindings": [
                    {"repo": "a/one", "triggers": {"pull_request": {}}},
                    {"repo": "a/two", "triggers": {"pull_request": {}}},
                ],
            },
        },
    )
    registry = build_github_agent_registry()
    assert len(lookup_agents(registry, "a/one", "pull_request")) == 1
    assert len(lookup_agents(registry, "a/two", "pull_request")) == 1
    assert lookup_agents(registry, "a/three", "pull_request") == []


def test_registry_scans_multiple_users(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "agent-a",
        {"name": "agent-a", "github": {"bindings": [{"repo": "x/y", "triggers": {"pull_request": {}}}]}},
    )
    _write_agent(
        base_dir,
        "alice",
        "agent-b",
        {"name": "agent-b", "github": {"bindings": [{"repo": "x/y", "triggers": {"pull_request": {}}}]}},
    )
    registry = build_github_agent_registry()
    matched = lookup_agents(registry, "x/y", "pull_request")
    user_ids = sorted(m.user_id for m in matched)
    assert user_ids == ["alice", "default"]


def test_registry_skips_broken_agent_config(base_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "good",
        {"name": "good", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    bad_dir = base_dir / "users" / "default" / "agents" / "broken"
    bad_dir.mkdir(parents=True)
    (bad_dir / "config.yaml").write_text("this: : not : valid\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="app.gateway.github.registry"):
        registry = build_github_agent_registry()
    assert any("broken" in rec.message for rec in caplog.records)
    matched = lookup_agents(registry, "a/b", "pull_request")
    assert [m.agent.name for m in matched] == ["good"]


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_registry_cache_returns_same_object_on_warm_call(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "alpha",
        {"name": "alpha", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    first = build_github_agent_registry()
    second = build_github_agent_registry()
    assert first is second  # 说明当前测试分支所验证的真实行为与边界。
    assert lookup_agents(first, "a/b", "pull_request")[0].agent.name == "alpha"


def test_registry_cache_invalidates_on_new_agent(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "alpha",
        {"name": "alpha", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    first = build_github_agent_registry()
    assert {m.agent.name for m in lookup_agents(first, "a/b", "pull_request")} == {"alpha"}

    _write_agent(
        base_dir,
        "default",
        "beta",
        {"name": "beta", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    second = build_github_agent_registry()
    assert second is not first
    assert {m.agent.name for m in lookup_agents(second, "a/b", "pull_request")} == {"alpha", "beta"}


def test_registry_cache_invalidates_on_config_edit(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    agent_dir = _write_agent(
        base_dir,
        "default",
        "edited",
        {"name": "edited", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    first = build_github_agent_registry()
    assert {m.agent.name for m in lookup_agents(first, "a/b", "pull_request")} == {"edited"}

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    import os
    import time

    (agent_dir / "config.yaml").write_text(
        yaml.safe_dump({"name": "edited", "github": {"bindings": [{"repo": "c/d", "triggers": {"pull_request": {}}}]}}),
        encoding="utf-8",
    )
    future = time.time() + 5
    os.utime(agent_dir / "config.yaml", (future, future))

    second = build_github_agent_registry()
    assert second is not first
    assert lookup_agents(second, "a/b", "pull_request") == []
    assert {m.agent.name for m in lookup_agents(second, "c/d", "pull_request")} == {"edited"}


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_registry_indexes_legacy_shared_agent(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_legacy_agent(
        base_dir,
        "shared-bot",
        {"name": "shared-bot", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    registry = build_github_agent_registry()
    matched = lookup_agents(registry, "a/b", "pull_request")
    assert len(matched) == 1
    assert matched[0].agent.name == "shared-bot"
    # 说明当前测试分支所验证的真实行为与边界。
    assert matched[0].user_id == "default"


def test_registry_per_user_entry_shadows_legacy_with_same_name(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    # 说明当前测试分支所验证的真实行为与边界。
    _write_legacy_agent(
        base_dir,
        "shadowed",
        {"name": "shadowed", "github": {"bindings": [{"repo": "legacy/repo", "triggers": {"pull_request": {}}}]}},
    )
    _write_agent(
        base_dir,
        "default",
        "shadowed",
        {"name": "shadowed", "github": {"bindings": [{"repo": "user/repo", "triggers": {"pull_request": {}}}]}},
    )
    registry = build_github_agent_registry()
    # 说明当前测试分支所验证的真实行为与边界。
    assert len(lookup_agents(registry, "user/repo", "pull_request")) == 1
    # 说明当前测试分支所验证的真实行为与边界。
    assert lookup_agents(registry, "legacy/repo", "pull_request") == []


def test_registry_legacy_cache_invalidates_on_legacy_config_edit(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    agent_dir = _write_legacy_agent(
        base_dir,
        "legacy-edited",
        {"name": "legacy-edited", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    first = build_github_agent_registry()
    assert {m.agent.name for m in lookup_agents(first, "a/b", "pull_request")} == {"legacy-edited"}

    import os
    import time

    (agent_dir / "config.yaml").write_text(
        yaml.safe_dump({"name": "legacy-edited", "github": {"bindings": [{"repo": "c/d", "triggers": {"pull_request": {}}}]}}),
        encoding="utf-8",
    )
    future = time.time() + 5
    os.utime(agent_dir / "config.yaml", (future, future))

    second = build_github_agent_registry()
    assert second is not first
    assert lookup_agents(second, "a/b", "pull_request") == []
    assert {m.agent.name for m in lookup_agents(second, "c/d", "pull_request")} == {"legacy-edited"}


def test_registry_cache_invalidates_on_agent_deletion(base_dir: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _write_agent(
        base_dir,
        "default",
        "alpha",
        {"name": "alpha", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    agent_dir = _write_agent(
        base_dir,
        "default",
        "doomed",
        {"name": "doomed", "github": {"bindings": [{"repo": "a/b", "triggers": {"pull_request": {}}}]}},
    )
    first = build_github_agent_registry()
    assert {m.agent.name for m in lookup_agents(first, "a/b", "pull_request")} == {"alpha", "doomed"}

    import shutil

    shutil.rmtree(agent_dir)
    second = build_github_agent_registry()
    assert second is not first
    assert {m.agent.name for m in lookup_agents(second, "a/b", "pull_request")} == {"alpha"}
