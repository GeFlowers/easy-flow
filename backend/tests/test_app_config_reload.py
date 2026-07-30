"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import deerflow.config.app_config as app_config_module
from deerflow.config.acp_config import load_acp_config_from_dict
from deerflow.config.agents_api_config import get_agents_api_config, load_agents_api_config_from_dict
from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config
from deerflow.config.checkpointer_config import get_checkpointer_config, load_checkpointer_config_from_dict
from deerflow.config.guardrails_config import get_guardrails_config, load_guardrails_config_from_dict
from deerflow.config.memory_config import get_memory_config, load_memory_config_from_dict
from deerflow.config.stream_bridge_config import get_stream_bridge_config, load_stream_bridge_config_from_dict
from deerflow.config.subagents_config import get_subagents_app_config, load_subagents_config_from_dict
from deerflow.config.summarization_config import get_summarization_config, load_summarization_config_from_dict
from deerflow.config.title_config import get_title_config, load_title_config_from_dict
from deerflow.config.tool_search_config import get_tool_search_config, load_tool_search_config_from_dict
from deerflow.runtime.checkpointer import get_checkpointer, reset_checkpointer
from deerflow.runtime.store import get_store, reset_store


def _reset_config_singletons() -> None:
    """为“重置配置该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    load_title_config_from_dict({})
    load_summarization_config_from_dict({})
    load_memory_config_from_dict({})
    load_agents_api_config_from_dict({})
    load_subagents_config_from_dict({})
    load_tool_search_config_from_dict({})
    load_guardrails_config_from_dict({})
    load_checkpointer_config_from_dict(None)
    load_stream_bridge_config_from_dict(None)
    load_acp_config_from_dict({})
    reset_checkpointer()
    reset_store()
    reset_app_config()


def _write_config(path: Path, *, model_name: str, supports_thinking: bool) -> None:
    """为“写入配置”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": model_name,
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                        "supports_thinking": supports_thinking,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_config_with_agents_api(
    path: Path,
    *,
    model_name: str,
    supports_thinking: bool,
    agents_api: dict | None = None,
) -> None:
    """为“写入配置使用智能体接口”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    config = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": model_name,
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
                "supports_thinking": supports_thinking,
            }
        ],
    }
    if agents_api is not None:
        config["agents_api"] = agents_api

    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _write_config_with_sections(path: Path, sections: dict | None = None) -> None:
    """为“写入配置使用配置段”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    config = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": "first-model",
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
            }
        ],
    }
    if sections:
        config.update(sections)

    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _write_extensions_config(path: Path) -> None:
    """为“写入该项配置”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")


def test_app_config_defaults_missing_database_to_sqlite(tmp_path, monkeypatch):
    """验证“应用配置该项缺失数据库该项轻量数据库”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="first-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))

    assert config.database.backend == "sqlite"
    assert config.database.sqlite_dir == ".deer-flow/data"


def test_app_config_defaults_empty_database_to_sqlite(tmp_path, monkeypatch):
    """验证“应用配置该项空值数据库该项轻量数据库”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "database": {},
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))

    assert config.database.backend == "sqlite"
    assert config.database.sqlite_dir == ".deer-flow/data"


def test_app_config_coerces_commented_out_list_sections(tmp_path, monkeypatch):
    """验证“应用配置该项该项该项列出配置段”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": None,
                "tools": None,
                "tool_groups": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))

    assert config.models == []
    assert config.tools == []
    assert config.tool_groups == []


def test_app_config_coerces_commented_out_object_sections(tmp_path, monkeypatch):
    """验证“应用配置该项该项该项对象配置段”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "memory": None,
                "summarization": None,
                "guardrails": None,
                "tool_output": None,
                "run_events": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))

    # 每个存在但为空的对象部分都会回退到真正的默认配置
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert type(config.memory).__name__ == "MemoryConfig"
    assert type(config.summarization).__name__ == "SummarizationConfig"
    assert type(config.guardrails).__name__ == "GuardrailsConfig"
    assert type(config.tool_output).__name__ == "ToolOutputConfig"
    assert type(config.run_events).__name__ == "RunEventsConfig"


def test_app_config_null_required_section_still_errors(tmp_path, monkeypatch):
    """验证“应用配置该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    config_path.write_text(yaml.safe_dump({"sandbox": None}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    with pytest.raises(ValidationError):
        AppConfig.from_file(str(config_path))


def test_app_config_warns_when_no_models_configured(tmp_path, monkeypatch, caplog):
    """验证“应用配置警告当没有模型被配置”的回归边界，固定缺省模型配置触发的告警内容与后续安全回退。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    with caplog.at_level("WARNING", logger="deerflow.config.app_config"):
        AppConfig.from_file(str(config_path))

    assert "No models are configured" in caplog.text


def test_get_app_config_reloads_when_file_changes(tmp_path, monkeypatch):
    """验证“获取应用配置该项当文件该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="first-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].supports_thinking is False

        _write_config(config_path, model_name="first-model", supports_thinking=True)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        reloaded = get_app_config()
        assert reloaded.models[0].supports_thinking is True
        assert reloaded is not initial
    finally:
        reset_app_config()


def test_get_app_config_reloads_when_content_digest_changes_without_metadata(tmp_path, monkeypatch):
    """验证“获取应用配置该项当内容摘要该项不使用元数据”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="model-a", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    _reset_config_singletons()

    try:
        initial = get_app_config()
        initial_mtime = app_config_module._app_config_mtime
        initial_signature = app_config_module._app_config_signature
        assert initial.models[0].name == "model-a"
        assert initial_signature is not None

        _write_config(config_path, model_name="model-b", supports_thinking=False)

        real_get_config_signature = app_config_module._get_config_signature

        def stale_metadata_signature(path: Path):
            """为“过期元数据签名”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            current_signature = real_get_config_signature(path)
            assert current_signature is not None
            return (initial_signature[0], initial_signature[1], current_signature[2])

        monkeypatch.setattr(app_config_module, "_get_config_mtime", lambda _path: initial_mtime)
        monkeypatch.setattr(app_config_module, "_get_config_signature", stale_metadata_signature)

        reloaded = get_app_config()
        assert reloaded.models[0].name == "model-b"
        assert reloaded is not initial
        assert app_config_module._app_config_signature is not None
        assert app_config_module._app_config_signature[:2] == initial_signature[:2]
        assert app_config_module._app_config_signature[2] != initial_signature[2]
    finally:
        _reset_config_singletons()


def test_get_app_config_reloads_when_config_path_changes(tmp_path, monkeypatch):
    """验证“获取应用配置该项当配置路径该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_a = tmp_path / "config-a.yaml"
    config_b = tmp_path / "config-b.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_a, model_name="model-a", supports_thinking=False)
    _write_config(config_b, model_name="model-b", supports_thinking=True)

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_a))
    reset_app_config()

    try:
        first = get_app_config()
        assert first.models[0].name == "model-a"

        monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_b))
        second = get_app_config()
        assert second.models[0].name == "model-b"
        assert second is not first
    finally:
        reset_app_config()


def test_get_app_config_resets_agents_api_config_when_section_removed(tmp_path, monkeypatch):
    """验证“获取应用配置该项智能体接口配置当该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_agents_api(
        config_path,
        model_name="first-model",
        supports_thinking=False,
        agents_api={"enabled": True},
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].name == "first-model"
        assert get_agents_api_config().enabled is True

        _write_config_with_agents_api(
            config_path,
            model_name="first-model",
            supports_thinking=False,
        )
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        reloaded = get_app_config()
        assert reloaded is not initial
        assert get_agents_api_config().enabled is False
    finally:
        reset_app_config()


def test_get_app_config_resets_singleton_configs_when_sections_removed(tmp_path, monkeypatch):
    """验证“获取应用配置该项单例该项当配置段该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_sections(
        config_path,
        {
            "title": {"enabled": False, "max_words": 3},
            "summarization": {"enabled": True},
            "memory": {"enabled": False, "max_facts": 50},
            "subagents": {"timeout_seconds": 42, "agents": {"reviewer": {"max_turns": 2}}},
            "tool_search": {"enabled": True},
            "guardrails": {"enabled": True, "fail_closed": False},
            "checkpointer": {"type": "memory"},
            "stream_bridge": {"type": "memory", "queue_maxsize": 12},
        },
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        get_app_config()
        assert get_title_config().enabled is False
        assert get_summarization_config().enabled is True
        assert get_memory_config().enabled is False
        assert get_subagents_app_config().timeout_seconds == 42
        assert get_tool_search_config().enabled is True
        assert get_guardrails_config().enabled is True
        assert get_checkpointer_config() is not None
        assert get_stream_bridge_config() is not None

        _write_config_with_sections(config_path)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        get_app_config()
        assert get_title_config().enabled is True
        assert get_summarization_config().enabled is False
        assert get_memory_config().enabled is True
        assert get_subagents_app_config().timeout_seconds == 1800
        assert get_tool_search_config().enabled is False
        assert get_guardrails_config().enabled is False
        assert get_checkpointer_config() is None
        assert get_stream_bridge_config() is None
    finally:
        _reset_config_singletons()


def test_get_app_config_resets_persistence_runtime_singletons_when_checkpointer_removed(tmp_path, monkeypatch):
    """验证“获取应用配置该项持久化运行时该项当该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_sections(config_path, {"checkpointer": {"type": "memory"}})

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_checkpointer()
    reset_store()
    reset_app_config()

    try:
        get_app_config()
        initial_checkpointer = get_checkpointer()
        initial_store = get_store()

        _write_config_with_sections(config_path)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        get_app_config()

        assert get_checkpointer_config() is None
        assert get_checkpointer() is not initial_checkpointer
        assert get_store() is not initial_store
    finally:
        _reset_config_singletons()


def test_get_app_config_keeps_persistence_runtime_singletons_when_checkpointer_unchanged(tmp_path, monkeypatch):
    """验证“获取应用配置保留持久化运行时该项当该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_sections(
        config_path,
        {
            "title": {"enabled": False},
            "checkpointer": {"type": "memory"},
        },
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    _reset_config_singletons()

    try:
        get_app_config()
        initial_checkpointer = get_checkpointer()
        initial_store = get_store()

        _write_config_with_sections(
            config_path,
            {
                "title": {"enabled": True},
                "checkpointer": {"type": "memory"},
            },
        )
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        get_app_config()

        assert get_checkpointer() is initial_checkpointer
        assert get_store() is initial_store
    finally:
        _reset_config_singletons()


def test_get_app_config_does_not_mutate_singletons_when_reload_validation_fails(tmp_path, monkeypatch):
    """验证“获取应用配置该项该项该项该项当重载该项失败”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_sections(
        config_path,
        {
            "title": {"enabled": False},
            "tool_search": {"enabled": True},
            "checkpointer": {"type": "memory"},
        },
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    _reset_config_singletons()

    try:
        previous_app_config = get_app_config()
        initial_checkpointer = get_checkpointer()
        initial_store = get_store()

        _write_config_with_sections(
            config_path,
            {
                "title": False,
                "tool_search": False,
                "checkpointer": {"type": "memory"},
            },
        )
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        with pytest.raises(ValidationError):
            get_app_config()

        assert app_config_module._app_config is previous_app_config
        assert get_title_config().enabled is False
        assert get_tool_search_config().enabled is True
        assert get_checkpointer_config() is not None
        assert get_checkpointer() is initial_checkpointer
        assert get_store() is initial_store
    finally:
        _reset_config_singletons()
