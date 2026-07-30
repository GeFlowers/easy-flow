"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

import json

import pytest
import yaml
from pydantic import ValidationError

from deerflow.config.acp_config import ACPAgentConfig, get_acp_agents, load_acp_config_from_dict
from deerflow.config.app_config import AppConfig


def setup_function():
    """执行“设置该项”的测试辅助步骤，维持断言所依赖的状态、失败分支与资源生命周期。"""
    load_acp_config_from_dict({})


def test_load_acp_config_sets_agents():
    """验证“加载智能体通信协议配置设置智能体”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    load_acp_config_from_dict(
        {
            "claude_code": {
                "command": "claude-code-acp",
                "args": [],
                "description": "Claude Code for coding tasks",
                "model": None,
            }
        }
    )
    agents = get_acp_agents()
    assert "claude_code" in agents
    assert agents["claude_code"].command == "claude-code-acp"
    assert agents["claude_code"].description == "Claude Code for coding tasks"
    assert agents["claude_code"].model is None


def test_load_acp_config_multiple_agents():
    """验证“加载智能体通信协议配置该项智能体”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    load_acp_config_from_dict(
        {
            "claude_code": {"command": "claude-code-acp", "args": [], "description": "Claude Code"},
            "codex": {"command": "codex-acp", "args": ["--flag"], "description": "Codex CLI"},
        }
    )
    agents = get_acp_agents()
    assert len(agents) == 2
    assert agents["codex"].args == ["--flag"]


def test_load_acp_config_empty_clears_agents():
    """验证“加载智能体通信协议配置空值清除智能体”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    load_acp_config_from_dict({"agent": {"command": "cmd", "args": [], "description": "desc"}})
    assert len(get_acp_agents()) == 1

    load_acp_config_from_dict({})
    assert len(get_acp_agents()) == 0


def test_load_acp_config_none_clears_agents():
    """验证“加载智能体通信协议配置空值清除智能体”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    load_acp_config_from_dict({"agent": {"command": "cmd", "args": [], "description": "desc"}})
    assert len(get_acp_agents()) == 1

    load_acp_config_from_dict(None)
    assert get_acp_agents() == {}


def test_acp_agent_config_defaults():
    """验证“智能体通信协议该项配置该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = ACPAgentConfig(command="my-agent", description="My agent")
    assert cfg.args == []
    assert cfg.env == {}
    assert cfg.model is None
    assert cfg.auto_approve_permissions is False


def test_acp_agent_config_env_literal():
    """验证“智能体通信协议该项配置环境变量该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = ACPAgentConfig(command="my-agent", description="desc", env={"OPENAI_API_KEY": "sk-test"})
    assert cfg.env == {"OPENAI_API_KEY": "sk-test"}


def test_acp_agent_config_env_default_is_empty():
    """验证“智能体通信协议该项配置环境变量默认值该项空值”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = ACPAgentConfig(command="my-agent", description="desc")
    assert cfg.env == {}


def test_load_acp_config_preserves_env():
    """验证“加载智能体通信协议配置保留环境变量”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    load_acp_config_from_dict(
        {
            "codex": {
                "command": "codex-acp",
                "args": [],
                "description": "Codex CLI",
                "env": {"OPENAI_API_KEY": "$OPENAI_API_KEY", "FOO": "bar"},
            }
        }
    )
    cfg = get_acp_agents()["codex"]
    assert cfg.env == {"OPENAI_API_KEY": "$OPENAI_API_KEY", "FOO": "bar"}


def test_acp_agent_config_with_model():
    """验证“智能体通信协议该项配置使用该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = ACPAgentConfig(command="my-agent", description="desc", model="claude-opus-4")
    assert cfg.model == "claude-opus-4"


def test_acp_agent_config_auto_approve_permissions():
    """验证“智能体通信协议该项配置该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = ACPAgentConfig(command="my-agent", description="desc", auto_approve_permissions=True)
    assert cfg.auto_approve_permissions is True


def test_acp_agent_config_missing_command_raises():
    """验证“智能体通信协议该项配置缺失命令抛出”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    with pytest.raises(ValidationError):
        ACPAgentConfig(description="No command provided")


def test_acp_agent_config_missing_description_raises():
    """验证“智能体通信协议该项配置缺失该项抛出”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    with pytest.raises(ValidationError):
        ACPAgentConfig(command="my-agent")


def test_get_acp_agents_returns_empty_by_default():
    """验证“获取智能体通信协议智能体返回空值该项默认值”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    load_acp_config_from_dict({})
    assert get_acp_agents() == {}


def test_app_config_reload_without_acp_agents_clears_previous_state(tmp_path, monkeypatch):
    """验证“应用配置重载不使用智能体通信协议智能体清除该项状态”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")

    config_with_acp = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": "test-model",
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
            }
        ],
        "acp_agents": {
            "codex": {
                "command": "codex-acp",
                "args": [],
                "description": "Codex CLI",
            }
        },
    }
    config_without_acp = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": "test-model",
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
            }
        ],
    }

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config_path.write_text(yaml.safe_dump(config_with_acp), encoding="utf-8")
    AppConfig.from_file(str(config_path))
    assert set(get_acp_agents()) == {"codex"}

    config_path.write_text(yaml.safe_dump(config_without_acp), encoding="utf-8")
    AppConfig.from_file(str(config_path))
    assert get_acp_agents() == {}
