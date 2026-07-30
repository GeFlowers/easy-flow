'未说明'

from types import SimpleNamespace

import pytest

from deerflow.config.subagents_config import (
    CustomSubagentConfig,
    SubagentOverrideConfig,
    SubagentsAppConfig,
    get_subagents_app_config,
    load_subagents_config_from_dict,
)
from deerflow.subagents.config import SubagentConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_subagents_config(**kwargs) -> None:
    '未说明'
    load_subagents_config_from_dict(kwargs)


# ---------------------------------------------------------------------------
# SubagentConfig.skills field
# ---------------------------------------------------------------------------


class TestSubagentConfigSkills:
    '未说明'
    def test_default_skills_is_none(self):
        '未说明'
        config = SubagentConfig(name="test", description="test", system_prompt="test")
        assert config.skills is None

    def test_skills_whitelist(self):
        '未说明'
        config = SubagentConfig(
            name="test",
            description="test",
            system_prompt="test",
            skills=["data-analysis", "visualization"],
        )
        assert config.skills == ["data-analysis", "visualization"]

    def test_skills_empty_list_means_no_skills(self):
        '未说明'
        config = SubagentConfig(
            name="test",
            description="test",
            system_prompt="test",
            skills=[],
        )
        assert config.skills == []


# ---------------------------------------------------------------------------
# SubagentOverrideConfig.skills field
# ---------------------------------------------------------------------------


class TestSubagentOverrideConfigSkills:
    '未说明'
    def test_default_skills_is_none(self):
        '未说明'
        override = SubagentOverrideConfig()
        assert override.skills is None

    def test_skills_whitelist(self):
        '未说明'
        override = SubagentOverrideConfig(skills=["web-search", "data-analysis"])
        assert override.skills == ["web-search", "data-analysis"]

    def test_skills_empty_list(self):
        '未说明'
        override = SubagentOverrideConfig(skills=[])
        assert override.skills == []

    def test_skills_coexists_with_other_fields(self):
        '未说明'
        override = SubagentOverrideConfig(
            timeout_seconds=300,
            model="gpt-5",
            skills=["my-skill"],
        )
        assert override.timeout_seconds == 300
        assert override.model == "gpt-5"
        assert override.skills == ["my-skill"]


# ---------------------------------------------------------------------------
# CustomSubagentConfig model
# ---------------------------------------------------------------------------


class TestCustomSubagentConfig:
    '未说明'
    def test_minimal_valid(self):
        '未说明'
        config = CustomSubagentConfig(
            description="A test agent",
            system_prompt="You are a test agent.",
        )
        assert config.description == "A test agent"
        assert config.system_prompt == "You are a test agent."
        assert config.tools is None
        assert config.disallowed_tools == ["task", "ask_clarification", "present_files"]
        assert config.skills is None
        assert config.model == "inherit"
        assert config.max_turns == 50
        assert config.timeout_seconds == 900

    def test_full_configuration(self):
        '未说明'
        config = CustomSubagentConfig(
            description="Data analysis specialist",
            system_prompt="You are a data analysis subagent.",
            tools=["bash", "read_file", "write_file"],
            disallowed_tools=["task"],
            skills=["data-analysis", "visualization"],
            model="qwen3:32b",
            max_turns=80,
            timeout_seconds=600,
        )
        assert config.tools == ["bash", "read_file", "write_file"]
        assert config.skills == ["data-analysis", "visualization"]
        assert config.model == "qwen3:32b"
        assert config.max_turns == 80
        assert config.timeout_seconds == 600

    def test_skills_empty_list_no_skills(self):
        '未说明'
        config = CustomSubagentConfig(
            description="test",
            system_prompt="test",
            skills=[],
        )
        assert config.skills == []

    def test_rejects_zero_max_turns(self):
        '未说明'
        with pytest.raises(ValueError):
            CustomSubagentConfig(
                description="test",
                system_prompt="test",
                max_turns=0,
            )

    def test_rejects_zero_timeout(self):
        '未说明'
        with pytest.raises(ValueError):
            CustomSubagentConfig(
                description="test",
                system_prompt="test",
                timeout_seconds=0,
            )


# ---------------------------------------------------------------------------
# SubagentsAppConfig.custom_agents and get_skills_for()
# ---------------------------------------------------------------------------


class TestSubagentsAppConfigCustomAgents:
    '未说明'
    def test_default_custom_agents_empty(self):
        '未说明'
        config = SubagentsAppConfig()
        assert config.custom_agents == {}

    def test_custom_agents_loaded(self):
        '未说明'
        config = SubagentsAppConfig(
            custom_agents={
                "analysis": CustomSubagentConfig(
                    description="Analysis agent",
                    system_prompt="You analyze data.",
                    skills=["data-analysis"],
                ),
            }
        )
        assert "analysis" in config.custom_agents
        assert config.custom_agents["analysis"].skills == ["data-analysis"]

    def test_multiple_custom_agents(self):
        '未说明'
        config = SubagentsAppConfig(
            custom_agents={
                "analysis": CustomSubagentConfig(
                    description="Analysis",
                    system_prompt="analyze",
                    skills=["data-analysis"],
                ),
                "researcher": CustomSubagentConfig(
                    description="Research",
                    system_prompt="research",
                    skills=["web-search"],
                ),
            }
        )
        assert len(config.custom_agents) == 2


class TestGetSkillsFor:
    '未说明'
    def test_returns_none_when_no_override(self):
        '未说明'
        config = SubagentsAppConfig()
        assert config.get_skills_for("general-purpose") is None
        assert config.get_skills_for("unknown") is None

    def test_returns_skills_whitelist(self):
        '未说明'
        config = SubagentsAppConfig(
            agents={
                "general-purpose": SubagentOverrideConfig(skills=["web-search", "coding"]),
            }
        )
        assert config.get_skills_for("general-purpose") == ["web-search", "coding"]

    def test_returns_empty_list_for_no_skills(self):
        '未说明'
        config = SubagentsAppConfig(
            agents={
                "bash": SubagentOverrideConfig(skills=[]),
            }
        )
        assert config.get_skills_for("bash") == []

    def test_returns_none_for_unrelated_agent(self):
        '未说明'
        config = SubagentsAppConfig(
            agents={
                "bash": SubagentOverrideConfig(skills=["web-search"]),
            }
        )
        assert config.get_skills_for("general-purpose") is None

    def test_returns_none_when_skills_not_set(self):
        '未说明'
        config = SubagentsAppConfig(
            agents={
                "bash": SubagentOverrideConfig(timeout_seconds=300),
            }
        )
        assert config.get_skills_for("bash") is None


# ---------------------------------------------------------------------------
# load_subagents_config_from_dict with skills and custom_agents
# ---------------------------------------------------------------------------


class TestLoadSubagentsConfigWithSkills:
    '未说明'
    def teardown_method(self):
        '未说明'
        _reset_subagents_config()

    def test_load_with_skills_override(self):
        '未说明'
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {
                    "general-purpose": {"skills": ["web-search", "data-analysis"]},
                },
            }
        )
        cfg = get_subagents_app_config()
        assert cfg.get_skills_for("general-purpose") == ["web-search", "data-analysis"]

    def test_load_with_empty_skills(self):
        '未说明'
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {
                    "bash": {"skills": []},
                },
            }
        )
        cfg = get_subagents_app_config()
        assert cfg.get_skills_for("bash") == []

    def test_load_with_custom_agents(self):
        '未说明'
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "custom_agents": {
                    "analysis": {
                        "description": "Data analysis specialist",
                        "system_prompt": "You are a data analysis subagent.",
                        "skills": ["data-analysis", "visualization"],
                        "tools": ["bash", "read_file"],
                        "max_turns": 80,
                        "timeout_seconds": 600,
                    },
                },
            }
        )
        cfg = get_subagents_app_config()
        assert "analysis" in cfg.custom_agents
        custom = cfg.custom_agents["analysis"]
        assert custom.skills == ["data-analysis", "visualization"]
        assert custom.tools == ["bash", "read_file"]
        assert custom.max_turns == 80
        assert custom.timeout_seconds == 600

    def test_load_with_both_overrides_and_custom(self):
        '未说明'
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {
                    "general-purpose": {"skills": ["web-search"]},
                },
                "custom_agents": {
                    "analysis": {
                        "description": "Analysis",
                        "system_prompt": "Analyze.",
                        "skills": ["data-analysis"],
                    },
                },
            }
        )
        cfg = get_subagents_app_config()
        assert cfg.get_skills_for("general-purpose") == ["web-search"]
        assert cfg.custom_agents["analysis"].skills == ["data-analysis"]


# ---------------------------------------------------------------------------
# Registry: custom agent lookup
# ---------------------------------------------------------------------------


class TestRegistryCustomAgentLookup:
    '未说明'
    def teardown_method(self):
        '未说明'
        _reset_subagents_config()

    def test_custom_agent_found(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "custom_agents": {
                    "analysis": {
                        "description": "Data analysis specialist",
                        "system_prompt": "You are a data analysis subagent.",
                        "skills": ["data-analysis"],
                        "tools": ["bash", "read_file"],
                        "max_turns": 80,
                        "timeout_seconds": 600,
                    },
                },
            }
        )
        config = get_subagent_config("analysis")
        assert config is not None
        assert config.name == "analysis"
        assert config.skills == ["data-analysis"]
        assert config.tools == ["bash", "read_file"]
        assert config.max_turns == 80
        assert config.timeout_seconds == 600
        assert config.model == "inherit"

    def test_custom_agent_found_from_explicit_app_config_without_global_config(self, monkeypatch):
        '未说明'
        from deerflow.subagents.registry import get_subagent_config

        def fail_get_subagents_app_config():
            """处理获取 配置相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            raise AssertionError("ambient get_subagents_app_config() must not be used when app_config is explicit")

        monkeypatch.setattr("deerflow.config.subagents_config.get_subagents_app_config", fail_get_subagents_app_config)

        app_config = SimpleNamespace(
            subagents=SubagentsAppConfig(
                custom_agents={
                    "analysis": CustomSubagentConfig(
                        description="Data analysis specialist",
                        system_prompt="You are a data analysis subagent.",
                        skills=["data-analysis"],
                    )
                }
            )
        )

        config = get_subagent_config("analysis", app_config=app_config)

        assert config is not None
        assert config.name == "analysis"
        assert config.skills == ["data-analysis"]

    def test_custom_agent_not_found(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_config

        _reset_subagents_config()
        assert get_subagent_config("nonexistent") is None

    def test_get_available_subagent_names_falls_back_when_subagents_app_config_lacks_sandbox(self, monkeypatch):
        '未说明'
        from deerflow.subagents import registry as registry_module
        from deerflow.subagents.registry import get_available_subagent_names

        captured: dict[str, tuple] = {}

        def fake_is_host_bash_allowed(*args, **kwargs):
            '未说明'
            captured["args"] = args
            return True

        monkeypatch.setattr(registry_module, "is_host_bash_allowed", fake_is_host_bash_allowed)

        get_available_subagent_names(app_config=SubagentsAppConfig())

        assert captured["args"] == ()

    def test_builtin_takes_priority_over_custom(self):
        '未说明'
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "custom_agents": {
                    "general-purpose": {
                        "description": "Custom override attempt",
                        "system_prompt": "Should not be used",
                    },
                },
            }
        )
        config = get_subagent_config("general-purpose")
        # Should get the builtin description, not the custom one
        assert config.description == BUILTIN_SUBAGENTS["general-purpose"].description

    def test_custom_agent_with_override(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "custom_agents": {
                    "analysis": {
                        "description": "Analysis",
                        "system_prompt": "Analyze.",
                        "timeout_seconds": 600,
                    },
                },
                "agents": {
                    "analysis": {"timeout_seconds": 300, "skills": ["overridden-skill"]},
                },
            }
        )
        config = get_subagent_config("analysis")
        assert config is not None
        assert config.timeout_seconds == 300  # Override applied
        assert config.skills == ["overridden-skill"]  # Override applied


# ---------------------------------------------------------------------------
# Registry: skills override on builtin agents
# ---------------------------------------------------------------------------


class TestRegistrySkillsOverride:
    '未说明'
    def teardown_method(self):
        '未说明'
        _reset_subagents_config()

    def test_skills_override_applied_to_builtin(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "agents": {
                    "general-purpose": {"skills": ["web-search", "data-analysis"]},
                },
            }
        )
        config = get_subagent_config("general-purpose")
        assert config.skills == ["web-search", "data-analysis"]

    def test_empty_skills_override(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "agents": {
                    "bash": {"skills": []},
                },
            }
        )
        config = get_subagent_config("bash")
        assert config.skills == []

    def test_no_skills_override_keeps_default(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_config

        _reset_subagents_config()
        config = get_subagent_config("general-purpose")
        assert config.skills is None  # Default: inherit all

    def test_skills_override_does_not_mutate_builtin(self):
        '未说明'
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "agents": {
                    "general-purpose": {"skills": ["web-search"]},
                },
            }
        )
        _ = get_subagent_config("general-purpose")
        assert BUILTIN_SUBAGENTS["general-purpose"].skills is None


# ---------------------------------------------------------------------------
# Registry: get_available_subagent_names merges custom types
# ---------------------------------------------------------------------------


class TestRegistryAvailableNames:
    '未说明'
    def teardown_method(self):
        '未说明'
        _reset_subagents_config()

    def test_includes_builtin_names(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_names

        _reset_subagents_config()
        names = get_subagent_names()
        assert "general-purpose" in names
        assert "bash" in names

    def test_includes_custom_names(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_names

        load_subagents_config_from_dict(
            {
                "custom_agents": {
                    "analysis": {
                        "description": "Analysis",
                        "system_prompt": "Analyze.",
                    },
                    "researcher": {
                        "description": "Research",
                        "system_prompt": "Research.",
                    },
                },
            }
        )
        names = get_subagent_names()
        assert "general-purpose" in names
        assert "bash" in names
        assert "analysis" in names
        assert "researcher" in names

    def test_no_duplicates_when_custom_name_matches_builtin(self):
        '未说明'
        from deerflow.subagents.registry import get_subagent_names

        load_subagents_config_from_dict(
            {
                "custom_agents": {
                    "general-purpose": {
                        "description": "Duplicate name",
                        "system_prompt": "test",
                    },
                },
            }
        )
        names = get_subagent_names()
        assert names.count("general-purpose") == 1


# ---------------------------------------------------------------------------
# Registry: list_subagents includes custom agents
# ---------------------------------------------------------------------------


class TestRegistryListSubagentsWithCustom:
    '未说明'
    def teardown_method(self):
        '未说明'
        _reset_subagents_config()

    def test_list_includes_custom_agents(self):
        '未说明'
        from deerflow.subagents.registry import list_subagents

        load_subagents_config_from_dict(
            {
                "custom_agents": {
                    "analysis": {
                        "description": "Analysis",
                        "system_prompt": "Analyze.",
                        "skills": ["data-analysis"],
                    },
                },
            }
        )
        configs = list_subagents()
        names = {c.name for c in configs}
        assert "general-purpose" in names
        assert "bash" in names
        assert "analysis" in names

    def test_list_custom_agent_has_correct_skills(self):
        '未说明'
        from deerflow.subagents.registry import list_subagents

        load_subagents_config_from_dict(
            {
                "custom_agents": {
                    "analysis": {
                        "description": "Analysis",
                        "system_prompt": "Analyze.",
                        "skills": ["data-analysis", "visualization"],
                    },
                },
            }
        )
        by_name = {c.name: c for c in list_subagents()}
        assert by_name["analysis"].skills == ["data-analysis", "visualization"]


# ---------------------------------------------------------------------------
# Skills filter passthrough: verify config.skills is used in task_tool assembly
# ---------------------------------------------------------------------------


class TestSkillsFilterPassthrough:
    '未说明'

    def test_none_skills_passes_none_to_prompt(self):
        '未说明'
        config = SubagentConfig(
            name="test",
            description="test",
            system_prompt="test",
            skills=None,
        )
        # Verify: set(None) would raise, so the code must check for None first
        available = set(config.skills) if config.skills is not None else None
        assert available is None

    def test_empty_skills_passes_empty_set(self):
        '未说明'
        config = SubagentConfig(
            name="test",
            description="test",
            system_prompt="test",
            skills=[],
        )
        available = set(config.skills) if config.skills is not None else None
        assert available == set()

    def test_skills_whitelist_passes_correct_set(self):
        '未说明'
        config = SubagentConfig(
            name="test",
            description="test",
            system_prompt="test",
            skills=["data-analysis", "web-search"],
        )
        available = set(config.skills) if config.skills is not None else None
        assert available == {"data-analysis", "web-search"}
