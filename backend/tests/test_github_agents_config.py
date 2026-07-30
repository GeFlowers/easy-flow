"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deerflow.config.agents_config import (
    AgentConfig,
    GitHubAgentConfig,
    GitHubBinding,
    GitHubTriggerConfig,
    load_agent_config,
)


def test_github_field_defaults_to_none() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    cfg = AgentConfig(name="solo")
    assert cfg.github is None


def test_github_block_parses_full_shape() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    cfg = AgentConfig(
        name="coding-llm-gateway",
        github={
            "installation_id": 123456,
            "bindings": [
                {
                    "repo": "zhfeng/llm-gateway",
                    "triggers": {
                        "pull_request": {"actions": ["opened", "reopened"]},
                        "issue_comment": {
                            "require_mention": True,
                            "allow_authors": ["zhfeng"],
                            "mention_login": "coding-llm-gateway-bot",
                        },
                    },
                }
            ],
        },
    )
    assert isinstance(cfg.github, GitHubAgentConfig)
    assert cfg.github.installation_id == 123456
    assert len(cfg.github.bindings) == 1
    binding = cfg.github.bindings[0]
    assert isinstance(binding, GitHubBinding)
    assert binding.repo == "zhfeng/llm-gateway"
    assert set(binding.triggers.keys()) == {"pull_request", "issue_comment"}
    pr = binding.triggers["pull_request"]
    assert isinstance(pr, GitHubTriggerConfig)
    assert pr.actions == ["opened", "reopened"]
    assert pr.require_mention is False
    assert pr.allow_authors == []
    comment = binding.triggers["issue_comment"]
    assert comment.require_mention is True
    assert comment.allow_authors == ["zhfeng"]
    assert comment.mention_login == "coding-llm-gateway-bot"


def test_github_block_minimal_uses_defaults() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    cfg = AgentConfig(name="x", github={})
    assert cfg.github is not None
    assert cfg.github.installation_id is None
    assert cfg.github.bindings == []
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert cfg.github.recursion_limit is None


def test_github_recursion_limit_parses() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    cfg = AgentConfig(name="refactorer", github={"recursion_limit": 500})
    assert cfg.github is not None
    assert cfg.github.recursion_limit == 500


def test_github_trigger_invalid_type_raises() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with pytest.raises(Exception):  # noqa: PT011 — pydantic ValidationError subclasses Exception
        AgentConfig(
            name="x",
            github={"bindings": [{"repo": "a/b", "triggers": {"pull_request": "not-an-object"}}]},
        )


def test_github_bindings_must_have_repo() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with pytest.raises(Exception):  # noqa: PT011
        AgentConfig(name="x", github={"bindings": [{"triggers": {}}]})


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def _write_agent(base: Path, user_id: str, name: str, body: dict) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    agent_dir = base / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")


def test_load_agent_config_reads_github_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # 说明当前测试分支所验证的真实行为与边界。
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    body = {
        "name": "coding-llm-gateway",
        "model": "claude-sonnet-4-6",
        "github": {
            "installation_id": 999,
            "bindings": [
                {
                    "repo": "zhfeng/llm-gateway",
                    "triggers": {
                        "pull_request": {"actions": ["opened"]},
                    },
                }
            ],
        },
    }
    _write_agent(tmp_path, "default", "coding-llm-gateway", body)

    cfg = load_agent_config("coding-llm-gateway", user_id="default")
    assert cfg is not None
    assert cfg.github is not None
    assert cfg.github.installation_id == 999
    assert cfg.github.bindings[0].repo == "zhfeng/llm-gateway"
    assert cfg.github.bindings[0].triggers["pull_request"].actions == ["opened"]


def test_load_agent_config_without_github_block_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    _write_agent(tmp_path, "default", "plain-agent", {"name": "plain-agent"})
    cfg = load_agent_config("plain-agent", user_id="default")
    assert cfg is not None
    assert cfg.github is None


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_duplicate_bindings_same_repo_rejected() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with pytest.raises(ValueError, match="duplicate repos"):
        GitHubAgentConfig(
            bindings=[
                GitHubBinding(repo="a/b", triggers={"pull_request": GitHubTriggerConfig()}),
                GitHubBinding(repo="a/b", triggers={"issue_comment": GitHubTriggerConfig()}),
            ],
        )


def test_duplicate_bindings_error_lists_offending_repo() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with pytest.raises(ValueError) as excinfo:
        GitHubAgentConfig(
            bindings=[
                GitHubBinding(repo="x/one"),
                GitHubBinding(repo="x/two"),
                GitHubBinding(repo="x/one"),
                GitHubBinding(repo="x/two"),
            ],
        )
    msg = str(excinfo.value)
    assert "x/one" in msg
    assert "x/two" in msg


def test_distinct_repo_bindings_allowed() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    cfg = GitHubAgentConfig(
        bindings=[
            GitHubBinding(repo="a/one"),
            GitHubBinding(repo="a/two"),
            GitHubBinding(repo="b/three"),
        ],
    )
    assert [b.repo for b in cfg.bindings] == ["a/one", "a/two", "b/three"]


def test_load_agent_config_rejects_duplicate_repo_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    agent_dir = tmp_path / "users" / "default" / "agents" / "broken"
    agent_dir.mkdir(parents=True)
    body = {
        "name": "broken",
        "github": {
            "bindings": [
                {"repo": "a/b", "triggers": {"pull_request": {}}},
                {"repo": "a/b", "triggers": {"issue_comment": {}}},
            ],
        },
    }
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate repos"):
        load_agent_config("broken", user_id="default")
