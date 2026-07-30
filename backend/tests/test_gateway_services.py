"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import json

import pytest

from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config


@pytest.fixture
def _stub_app_config():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def test_format_sse_basic():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import format_sse

    frame = format_sse("metadata", {"run_id": "abc"})
    assert frame.startswith("event: metadata\n")
    assert "data: " in frame
    parsed = json.loads(frame.split("data: ")[1].split("\n")[0])
    assert parsed["run_id"] == "abc"


def test_format_sse_with_event_id():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import format_sse

    frame = format_sse("metadata", {"run_id": "abc"}, event_id="123-0")
    assert "id: 123-0" in frame


def test_format_sse_end_event_null():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import format_sse

    frame = format_sse("end", None)
    assert "data: null" in frame


def test_format_sse_no_event_id():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import format_sse

    frame = format_sse("values", {"x": 1})
    assert "id:" not in frame


def test_sanitize_log_param_strips_control_characters():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.utils import sanitize_log_param

    assert sanitize_log_param("thread\nid\rwith\x00controls") == "threadidwithcontrols"


def test_normalize_stream_modes_none():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes(None) == ["values"]


def test_normalize_stream_modes_string():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes("messages-tuple") == ["messages-tuple"]


def test_normalize_stream_modes_list():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes(["values", "messages-tuple"]) == ["values", "messages-tuple"]


def test_normalize_stream_modes_empty_list():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes([]) == ["values"]


def test_normalize_input_none():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_input

    assert normalize_input(None) == {}


def test_normalize_input_with_messages():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_input

    result = normalize_input({"messages": [{"role": "user", "content": "hi"}]})
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == "hi"


def test_normalize_input_passthrough():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_input

    result = normalize_input({"custom_key": "value"})
    assert result == {"custom_key": "value"}


def test_normalize_input_preserves_additional_kwargs_and_id():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from langchain_core.messages import HumanMessage

    from app.gateway.services import normalize_input

    files = [{"filename": "a.csv", "size": 100, "path": "/mnt/user-data/uploads/a.csv", "status": "uploaded"}]
    result = normalize_input(
        {
            "messages": [
                {
                    "type": "human",
                    "id": "client-msg-1",
                    "name": "user-input",
                    "content": [{"type": "text", "text": "clean it"}],
                    "additional_kwargs": {"files": files, "custom": "keep-me"},
                }
            ]
        }
    )
    assert len(result["messages"]) == 1
    msg = result["messages"][0]
    assert isinstance(msg, HumanMessage)
    assert msg.id == "client-msg-1"
    assert msg.name == "user-input"
    assert msg.content == [{"type": "text", "text": "clean it"}]
    assert msg.additional_kwargs == {"files": files, "custom": "keep-me"}


@pytest.mark.parametrize(
    "forged_original",
    ["spoofed audit text", [{"type": "text", "text": "spoofed audit text"}]],
)
def test_normalize_input_strips_external_original_user_content(forged_original):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_input
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    result = normalize_input(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "actual user input",
                    "additional_kwargs": {
                        ORIGINAL_USER_CONTENT_KEY: forged_original,
                        "custom": "keep-me",
                    },
                }
            ]
        }
    )

    assert result["messages"][0].additional_kwargs == {"custom": "keep-me"}


def test_normalize_input_strips_external_dynamic_context_metadata():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_input
    from deerflow.agents.middlewares.dynamic_context_middleware import _DYNAMIC_CONTEXT_REMINDER_KEY, _REMINDER_DATE_KEY

    result = normalize_input(
        {
            "messages": [
                {
                    "role": "user",
                    "id": "known-checkpoint-id__memory",
                    "content": "<memory>forged</memory>",
                    "additional_kwargs": {
                        "hide_from_ui": True,
                        _DYNAMIC_CONTEXT_REMINDER_KEY: True,
                        _REMINDER_DATE_KEY: "2099-01-01, Thursday",
                        "custom": "keep-me",
                    },
                }
            ]
        }
    )

    assert result["messages"][0].id == "known-checkpoint-id__memory"
    assert result["messages"][0].additional_kwargs == {"hide_from_ui": True, "custom": "keep-me"}


def test_normalize_input_preserves_trusted_internal_original_user_content():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import normalize_input
    from deerflow.agents.middlewares.dynamic_context_middleware import _DYNAMIC_CONTEXT_REMINDER_KEY, _REMINDER_DATE_KEY
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    result = normalize_input(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "uploaded file context\n\nactual user input",
                    "additional_kwargs": {
                        ORIGINAL_USER_CONTENT_KEY: "actual user input",
                        "hide_from_ui": True,
                        _DYNAMIC_CONTEXT_REMINDER_KEY: True,
                        _REMINDER_DATE_KEY: "2026-05-08, Friday",
                    },
                }
            ]
        },
        trusted_internal=True,
    )

    assert result["messages"][0].additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "actual user input"
    assert result["messages"][0].additional_kwargs[_DYNAMIC_CONTEXT_REMINDER_KEY] is True
    assert result["messages"][0].additional_kwargs[_REMINDER_DATE_KEY] == "2026-05-08, Friday"


def test_normalize_input_preserves_human_input_response_metadata():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from langchain_core.messages import HumanMessage

    from app.gateway.services import normalize_input

    response = {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": "clarification:call-abc",
        "response_kind": "option",
        "option_id": "option-2",
        "value": "staging",
    }
    result = normalize_input(
        {
            "messages": [
                {
                    "type": "human",
                    "content": [{"type": "text", "text": "For your clarification, my answer is: staging"}],
                    "additional_kwargs": {"hide_from_ui": True, "human_input_response": response},
                }
            ]
        }
    )

    msg = result["messages"][0]
    assert isinstance(msg, HumanMessage)
    assert msg.additional_kwargs["hide_from_ui"] is True
    assert msg.additional_kwargs["human_input_response"] == response


def test_normalize_input_passes_through_basemessage_instances():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from langchain_core.messages import HumanMessage

    from app.gateway.services import normalize_input

    msg = HumanMessage(content="hello", id="m-1", additional_kwargs={"files": [{"filename": "x"}]})
    result = normalize_input({"messages": [msg]})
    assert result["messages"][0] is msg


def test_normalize_input_rejects_malformed_message_with_400():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import pytest
    from fastapi import HTTPException

    from app.gateway.services import normalize_input

    with pytest.raises(HTTPException) as excinfo:
        normalize_input({"messages": [{"role": "human", "content": "ok"}, {"oops": "no role here"}]})
    assert excinfo.value.status_code == 400
    assert "input.messages[1]" in excinfo.value.detail


def test_normalize_input_handles_non_human_roles():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

    from app.gateway.services import normalize_input

    result = normalize_input(
        {
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "ai", "content": "hi", "id": "ai-1"},
                {"role": "tool", "content": "result", "tool_call_id": "call-1"},
            ]
        }
    )
    types = [type(m) for m in result["messages"]]
    assert types == [SystemMessage, AIMessage, ToolMessage]
    assert result["messages"][1].id == "ai-1"
    assert result["messages"][2].tool_call_id == "call-1"


def test_build_run_config_basic():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None)
    assert config["configurable"]["thread_id"] == "thread-1"
    assert config["recursion_limit"] == 100


def test_build_run_config_with_overrides():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"model_name": "gpt-4"}, "tags": ["test"]},
        {"user": "alice"},
    )
    assert config["configurable"]["model_name"] == "gpt-4"
    assert config["tags"] == ["test"]
    assert config["metadata"]["user"] == "alice"


def test_build_run_config_context_path_still_sets_configurable_thread_id(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"context": {"secrets": {"ERP_TOKEN": "v"}}}, None)
    assert config["context"]["secrets"] == {"ERP_TOKEN": "v"}
    assert config["context"]["thread_id"] == "thread-1"
    assert config["configurable"]["thread_id"] == "thread-1"
    # 说明当前测试分支所验证的真实行为与边界。
    assert "secrets" not in config["configurable"]


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_build_run_config_clamps_excessive_recursion_limit(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"recursion_limit": 100_000_000}, None)
    assert config["recursion_limit"] == 1000


def test_build_run_config_ceiling_is_configurable(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config

    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "max_recursion_limit": 300}))
    try:
        config = build_run_config("thread-1", {"recursion_limit": 100_000_000}, None)
        assert config["recursion_limit"] == 300
    finally:
        reset_app_config()


def test_build_run_config_allows_recursion_limit_at_ceiling(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"recursion_limit": 1000}, None)
    assert config["recursion_limit"] == 1000


def test_build_run_config_preserves_reasonable_recursion_limit(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"recursion_limit": 250}, None)
    assert config["recursion_limit"] == 250


def test_build_run_config_rejects_invalid_recursion_limit(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import _DEFAULT_RECURSION_LIMIT, build_run_config

    for bad in (0, -5, "1000", 3.5, True, None):
        config = build_run_config("thread-1", {"recursion_limit": bad}, None)
        assert config["recursion_limit"] == _DEFAULT_RECURSION_LIMIT, bad


def test_build_run_config_clamps_recursion_limit_with_context(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"thread_id": "thread-1"}, "recursion_limit": 999_999},
        None,
    )
    assert config["recursion_limit"] == 1000


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_build_run_config_custom_agent_injects_agent_name():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id="finalis")
    assert config["configurable"]["agent_name"] == "finalis"
    assert config["run_name"] == "finalis"


def test_build_run_config_lead_agent_no_agent_name():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id="lead_agent")
    assert "agent_name" not in config["configurable"]
    assert "run_name" not in config


def test_build_run_config_none_assistant_id_no_agent_name():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id=None)
    assert "agent_name" not in config["configurable"]
    assert "run_name" not in config


def test_build_run_config_explicit_agent_name_not_overwritten():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"agent_name": "explicit-agent"}},
        None,
        assistant_id="other-agent",
    )
    assert config["configurable"]["agent_name"] == "explicit-agent"
    assert config["context"]["agent_name"] == "explicit-agent"
    assert config["run_name"] == "explicit-agent"


def test_build_run_config_context_custom_agent_injects_agent_name():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"model_name": "deepseek-v3"}},
        None,
        assistant_id="finalis",
    )

    assert config["context"]["agent_name"] == "finalis"
    assert config["configurable"]["agent_name"] == "finalis"


def test_resolve_agent_factory_returns_make_lead_agent():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import resolve_agent_factory
    from deerflow.agents.lead_agent.agent import make_lead_agent

    assert resolve_agent_factory(None) is make_lead_agent
    assert resolve_agent_factory("lead_agent") is make_lead_agent
    assert resolve_agent_factory("finalis") is make_lead_agent
    assert resolve_agent_factory("custom-agent-123") is make_lead_agent


def test_build_run_config_configurable_custom_agent_dual_writes_agent_name():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id="finalis")

    assert config["configurable"]["agent_name"] == "finalis"
    assert config["context"]["agent_name"] == "finalis"


def test_build_run_config_context_explicit_agent_name_not_overwritten():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"agent_name": "explicit-agent"}},
        None,
        assistant_id="other-agent",
    )

    assert config["context"]["agent_name"] == "explicit-agent"
    assert config["configurable"]["agent_name"] == "explicit-agent"
    assert config["run_name"] == "explicit-agent"


def test_build_run_config_dual_write_matches_merge_run_context_overrides_shape():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    via_assistant_id = build_run_config("thread-1", None, None, assistant_id="finalis")

    via_context = build_run_config("thread-1", None, None)
    merge_run_context_overrides(via_context, {"agent_name": "finalis"})

    assert via_assistant_id["configurable"]["agent_name"] == via_context["configurable"]["agent_name"]
    assert via_assistant_id["context"]["agent_name"] == via_context["context"]["agent_name"]


def test_non_interactive_context_override_is_internal_only():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"non_interactive": True})

    assert "non_interactive" not in config["configurable"]
    assert "non_interactive" not in config["context"]


def test_non_interactive_context_override_honored_for_internal_caller():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"non_interactive": True, "model_name": "gpt"}, internal=True)

    assert config["configurable"]["non_interactive"] is True
    assert config["context"]["non_interactive"] is True
    assert config["configurable"]["model_name"] == "gpt"


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_run_create_request_accepts_context():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.routers.thread_runs import RunCreateRequest

    body = RunCreateRequest(
        input={"messages": [{"role": "user", "content": "hi"}]},
        context={
            "model_name": "deepseek-v3",
            "thinking_enabled": True,
            "is_plan_mode": True,
            "subagent_enabled": True,
            "thread_id": "some-thread-id",
        },
    )
    assert body.context is not None
    assert body.context["model_name"] == "deepseek-v3"
    assert body.context["is_plan_mode"] is True
    assert body.context["subagent_enabled"] is True


def test_run_create_request_context_defaults_to_none():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.routers.thread_runs import RunCreateRequest

    body = RunCreateRequest(input=None)
    assert body.context is None


def test_apply_checkpoint_to_run_config_writes_checkpoint_fields():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio
    from types import SimpleNamespace

    from app.gateway.services import apply_checkpoint_to_run_config

    class FakeCheckpointer:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def __init__(self):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            self.seen_config = None

        async def aget_tuple(self, config):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            self.seen_config = config
            return SimpleNamespace(config=config, checkpoint={"channel_values": {}})

    checkpointer = FakeCheckpointer()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=checkpointer)))
    body = SimpleNamespace(
        checkpoint={
            "checkpoint_ns": "",
            "checkpoint_id": "ckpt-1",
            "checkpoint_map": {"": "ckpt-1"},
        },
        checkpoint_id=None,
    )
    config = {"configurable": {"thread_id": "thread-1"}}

    asyncio.run(apply_checkpoint_to_run_config(config, body=body, thread_id="thread-1", request=request))

    assert checkpointer.seen_config == {
        "configurable": {
            "thread_id": "thread-1",
            "checkpoint_ns": "",
            "checkpoint_id": "ckpt-1",
            "checkpoint_map": {"": "ckpt-1"},
        }
    }
    assert config["configurable"]["checkpoint_id"] == "ckpt-1"
    assert config["configurable"]["checkpoint_ns"] == ""
    assert config["configurable"]["checkpoint_map"] == {"": "ckpt-1"}


def test_apply_checkpoint_to_run_config_rejects_missing_checkpoint():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.gateway.services import apply_checkpoint_to_run_config

    class FakeCheckpointer:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        async def aget_tuple(self, config):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            return None

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=FakeCheckpointer())))
    body = SimpleNamespace(checkpoint=None, checkpoint_id="missing")
    config = {"configurable": {"thread_id": "thread-1"}}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(apply_checkpoint_to_run_config(config, body=body, thread_id="thread-1", request=request))

    assert exc.value.status_code == 404
    assert "missing" in exc.value.detail


def test_context_merges_into_configurable():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    # 说明当前测试分支所验证的真实行为与边界。
    config = build_run_config("thread-1", None, None)

    context = {
        "model_name": "deepseek-v3",
        "mode": "ultra",
        "reasoning_effort": "high",
        "thinking_enabled": True,
        "is_plan_mode": True,
        "subagent_enabled": True,
        "max_concurrent_subagents": 5,
        "max_total_subagents": 8,
        "thread_id": "should-be-ignored",
    }

    _CONTEXT_CONFIGURABLE_KEYS = {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "max_total_subagents",
    }
    configurable = config.setdefault("configurable", {})
    for key in _CONTEXT_CONFIGURABLE_KEYS:
        if key in context:
            configurable.setdefault(key, context[key])

    assert config["configurable"]["model_name"] == "deepseek-v3"
    assert config["configurable"]["thinking_enabled"] is True
    assert config["configurable"]["is_plan_mode"] is True
    assert config["configurable"]["subagent_enabled"] is True
    assert config["configurable"]["max_concurrent_subagents"] == 5
    assert config["configurable"]["max_total_subagents"] == 8
    assert config["configurable"]["reasoning_effort"] == "high"
    assert config["configurable"]["mode"] == "ultra"
    # 说明当前测试分支所验证的真实行为与边界。
    assert config["configurable"]["thread_id"] == "thread-1"
    # 说明当前测试分支所验证的真实行为与边界。
    assert "thread_id" not in {k for k in context if k in _CONTEXT_CONFIGURABLE_KEYS}


def test_merge_run_context_overrides_propagates_to_runtime_context():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"agent_name": "my-agent", "is_bootstrap": True, "thread_id": "ignored"})

    assert config["configurable"]["agent_name"] == "my-agent"
    assert config["configurable"]["is_bootstrap"] is True
    assert config["context"]["agent_name"] == "my-agent"
    assert config["context"]["is_bootstrap"] is True
    # 说明当前测试分支所验证的真实行为与边界。
    assert "thread_id" not in config["context"]


def test_merge_run_context_overrides_forwards_subagent_total_limit():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"max_total_subagents": 8})

    assert config["configurable"]["max_total_subagents"] == 8
    assert config["context"]["max_total_subagents"] == 8


def test_merge_run_context_overrides_noop_for_empty_context():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    before = {k: dict(v) if isinstance(v, dict) else v for k, v in config.items()}
    merge_run_context_overrides(config, None)
    merge_run_context_overrides(config, {})
    assert config == before


def test_merge_run_context_overrides_forwards_context_only_keys():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(
        config,
        {
            "github_token": "ghs_installation_token",
            "disable_clarification": True,
            "agent_name": "coding-llm-gateway",
        },
    )

    # 说明当前测试分支所验证的真实行为与边界。
    assert config["context"]["github_token"] == "ghs_installation_token"
    assert config["context"]["disable_clarification"] is True
    assert config["context"]["agent_name"] == "coding-llm-gateway"

    # 说明当前测试分支所验证的真实行为与边界。
    assert "github_token" not in config.get("configurable", {})
    assert "disable_clarification" not in config.get("configurable", {})


def test_merge_run_context_overrides_context_only_keys_do_not_override_existing():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    config["context"] = {"github_token": "pre-existing"}
    merge_run_context_overrides(config, {"github_token": "attacker-supplied"})

    assert config["context"]["github_token"] == "pre-existing"


def test_context_does_not_override_existing_configurable():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"model_name": "gpt-4", "is_plan_mode": False}},
        None,
    )

    context = {
        "model_name": "deepseek-v3",
        "is_plan_mode": True,
        "subagent_enabled": True,
    }

    _CONTEXT_CONFIGURABLE_KEYS = {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "max_total_subagents",
    }
    configurable = config.setdefault("configurable", {})
    for key in _CONTEXT_CONFIGURABLE_KEYS:
        if key in context:
            configurable.setdefault(key, context[key])

    # 说明当前测试分支所验证的真实行为与边界。
    assert config["configurable"]["model_name"] == "gpt-4"
    assert config["configurable"]["is_plan_mode"] is False
    # 说明当前测试分支所验证的真实行为与边界。
    assert config["configurable"]["subagent_enabled"] is True


def test_inject_authenticated_user_context_overrides_client_user_id():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from types import SimpleNamespace

    from app.gateway.services import build_run_config, inject_authenticated_user_context

    config = build_run_config("thread-1", None, None)
    config["context"] = {"user_id": "spoofed-client"}
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="auth-user-42")))

    inject_authenticated_user_context(config, request)

    assert config["context"]["user_id"] == "auth-user-42"


def test_merge_run_context_overrides_propagates_user_id():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", None, None)
    merge_run_context_overrides(config, {"user_id": "channel-user-7"})

    assert config["context"]["user_id"] == "channel-user-7"


def test_merge_run_context_overrides_does_not_clobber_existing_user_id():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, merge_run_context_overrides

    config = build_run_config("thread-1", {"context": {"user_id": "auth-user-42"}}, None)
    merge_run_context_overrides(config, {"user_id": "spoofed-client"})

    assert config["context"]["user_id"] == "auth-user-42"


def test_inject_authenticated_user_context_skips_internal_role():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from types import SimpleNamespace

    from app.gateway.services import build_run_config, inject_authenticated_user_context

    config = build_run_config("thread-1", None, None)
    config["context"] = {"user_id": "channel-user-7"}
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="internal-bot", system_role="internal")))

    inject_authenticated_user_context(config, request)

    assert config["context"]["user_id"] == "channel-user-7"


def test_inject_authenticated_user_context_strips_internal_spoofed_attribution():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from types import SimpleNamespace

    from app.gateway.services import build_run_config, inject_authenticated_user_context

    config = build_run_config(
        "thread-1",
        {
            "context": {
                "user_id": "channel-user-7",
                "user_role": "admin",
                "oauth_provider": "spoofed-provider",
                "oauth_id": "spoofed-subject",
            }
        },
        None,
    )
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="internal-bot", system_role="internal")))

    inject_authenticated_user_context(config, request)

    assert config["context"]["user_id"] == "channel-user-7"
    assert "user_role" not in config["context"]
    assert "oauth_provider" not in config["context"]
    assert "oauth_id" not in config["context"]


async def _capture_start_run_graph_input(body, *, auth_source=None):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from types import SimpleNamespace
    from unittest.mock import patch

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway.services import start_run
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    run_manager = RunManager(store=MemoryRunStore())
    state = SimpleNamespace(
        stream_bridge=SimpleNamespace(),
        run_manager=run_manager,
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
        run_event_store=SimpleNamespace(),
        run_events_config=None,
        thread_store=MemoryThreadMetaStore(InMemoryStore()),
    )
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=auth_source),
        app=SimpleNamespace(state=state),
    )
    captured: dict[str, object] = {}

    async def fake_run_agent(*args, **kwargs):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        captured["graph_input"] = kwargs["graph_input"]

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
    ):
        record = await start_run(body, "thread-command-test", request)
        await record.task

    return captured["graph_input"]


def test_start_run_translates_resume_command_to_langgraph_command(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio

    from langgraph.types import Command

    from app.gateway.routers.thread_runs import RunCreateRequest

    graph_input = asyncio.run(
        _capture_start_run_graph_input(
            RunCreateRequest(
                input=None,
                command={"resume": {"answer": "approved"}},
            )
        )
    )

    assert isinstance(graph_input, Command)
    assert graph_input.resume == {"answer": "approved"}


def test_start_run_uses_normalized_input_without_command(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio

    from langchain_core.messages import HumanMessage

    from app.gateway.routers.thread_runs import RunCreateRequest

    graph_input = asyncio.run(
        _capture_start_run_graph_input(
            RunCreateRequest(
                input={"messages": [{"role": "human", "content": "hi"}]},
                command=None,
            )
        )
    )

    assert isinstance(graph_input, dict)
    assert isinstance(graph_input["messages"][0], HumanMessage)
    assert graph_input["messages"][0].content == "hi"


def test_start_run_strips_external_original_user_content(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio

    from app.gateway.routers.thread_runs import RunCreateRequest
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    graph_input = asyncio.run(
        _capture_start_run_graph_input(
            RunCreateRequest(
                input={
                    "messages": [
                        {
                            "role": "human",
                            "content": "actual user input",
                            "additional_kwargs": {ORIGINAL_USER_CONTENT_KEY: "spoofed audit text"},
                        }
                    ]
                },
                command=None,
            )
        )
    )

    assert ORIGINAL_USER_CONTENT_KEY not in graph_input["messages"][0].additional_kwargs


def test_start_run_preserves_internal_original_user_content(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio

    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
    from app.gateway.routers.thread_runs import RunCreateRequest
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    graph_input = asyncio.run(
        _capture_start_run_graph_input(
            RunCreateRequest(
                input={
                    "messages": [
                        {
                            "role": "human",
                            "content": "uploaded file context\n\nactual user input",
                            "additional_kwargs": {ORIGINAL_USER_CONTENT_KEY: "actual user input"},
                        }
                    ]
                },
                command=None,
            ),
            auth_source=AUTH_SOURCE_INTERNAL,
        )
    )

    assert graph_input["messages"][0].additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "actual user input"


def test_start_run_uses_internal_owner_header_for_persistence(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE
    from app.gateway.services import start_run
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore
    from deerflow.runtime.user_context import get_effective_user_id

    async def _scenario():
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        run_store = MemoryRunStore()
        thread_store = MemoryThreadMetaStore(InMemoryStore())
        await thread_store.create("channel-thread", user_id="default", metadata={"legacy": True})
        run_manager = RunManager(store=run_store)
        state = SimpleNamespace(
            stream_bridge=SimpleNamespace(),
            run_manager=run_manager,
            checkpointer=InMemorySaver(),
            store=InMemoryStore(),
            run_event_store=SimpleNamespace(),
            run_events_config=None,
            thread_store=thread_store,
        )
        request = SimpleNamespace(
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
            state=SimpleNamespace(user=SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)),
            app=SimpleNamespace(state=state),
        )
        body = SimpleNamespace(
            assistant_id="lead_agent",
            input={"messages": [{"role": "human", "content": "hi"}]},
            metadata={},
            config=None,
            context=None,
            on_disconnect="cancel",
            multitask_strategy="reject",
            stream_mode=None,
            stream_subgraphs=False,
            interrupt_before=None,
            interrupt_after=None,
        )
        task_context: dict[str, str] = {}

        async def fake_run_agent(*args, **kwargs):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            task_context["user_id"] = get_effective_user_id()

        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
        ):
            record = await start_run(body, "channel-thread", request)
            await record.task

        owner_run = await run_store.get(record.run_id, user_id="owner-1")
        default_run = await run_store.get(record.run_id, user_id="default")
        owner_thread = await thread_store.get("channel-thread", user_id="owner-1")
        default_thread = await thread_store.get("channel-thread", user_id="default")
        return owner_run, default_run, owner_thread, default_thread, task_context

    owner_run, default_run, owner_thread, default_thread, task_context = asyncio.run(_scenario())

    assert owner_run is not None
    assert owner_run["user_id"] == "owner-1"
    assert default_run is None
    assert owner_thread is not None
    assert owner_thread["user_id"] == "owner-1"
    assert owner_thread["metadata"] == {"legacy": True}
    assert default_thread is None
    assert task_context["user_id"] == "owner-1"


def test_start_run_stamps_internal_owner_guardrail_attribution(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE
    from app.gateway.services import start_run
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    class _Provider:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        async def get_user(self, user_id: str):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            assert user_id == "owner-1"
            return SimpleNamespace(
                id="owner-1",
                system_role="user",
                oauth_provider="keycloak",
                oauth_id="subject-123",
            )

    async def _scenario():
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        thread_store = MemoryThreadMetaStore(InMemoryStore())
        await thread_store.create("channel-thread", user_id="owner-1", metadata={})
        run_manager = RunManager(store=MemoryRunStore())
        state = SimpleNamespace(
            stream_bridge=SimpleNamespace(),
            run_manager=run_manager,
            checkpointer=InMemorySaver(),
            store=InMemoryStore(),
            run_event_store=SimpleNamespace(),
            run_events_config=None,
            thread_store=thread_store,
        )
        request = SimpleNamespace(
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
            state=SimpleNamespace(user=SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)),
            app=SimpleNamespace(state=state),
        )
        body = SimpleNamespace(
            assistant_id="lead_agent",
            input={"messages": [{"role": "human", "content": "hi"}]},
            metadata={},
            config={
                "context": {
                    "user_role": "admin",
                    "oauth_provider": "spoofed-provider",
                    "oauth_id": "spoofed-subject",
                }
            },
            context={"user_id": "spoofed-client"},
            on_disconnect="cancel",
            multitask_strategy="reject",
            stream_mode=None,
            stream_subgraphs=False,
            interrupt_before=None,
            interrupt_after=None,
        )
        captured_context: dict[str, object] = {}

        async def fake_run_agent(*args, **kwargs):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            captured_context.update(kwargs["config"]["context"])

        with (
            patch("app.gateway.services.get_local_provider", return_value=_Provider()),
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
        ):
            record = await start_run(body, "channel-thread", request)
            await record.task

        return captured_context

    context = asyncio.run(_scenario())

    assert context["user_id"] == "owner-1"
    assert context["user_role"] == "user"
    assert context["oauth_provider"] == "keycloak"
    assert context["oauth_id"] == "subject-123"


def test_launch_scheduled_thread_run_marks_context_non_interactive(_stub_app_config):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.gateway.services import launch_scheduled_thread_run

    async def _scenario():
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        captured: dict[str, object] = {}

        async def fake_start_run(body, thread_id, request):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            captured["thread_id"] = thread_id
            captured["context"] = body.context
            captured["metadata"] = body.metadata
            return SimpleNamespace(run_id="run-1", thread_id=thread_id)

        with patch("app.gateway.services.start_run", side_effect=fake_start_run):
            result = await launch_scheduled_thread_run(
                thread_id="thread-scheduled",
                assistant_id="lead_agent",
                prompt="Run in background",
                app=SimpleNamespace(state=SimpleNamespace()),
                owner_user_id="user-1",
                metadata={"scheduled_task_id": "task-1"},
            )
        return captured, result

    captured, result = asyncio.run(_scenario())

    assert captured["thread_id"] == "thread-scheduled"
    assert captured["context"] == {"non_interactive": True, "user_id": "user-1"}
    assert captured["metadata"] == {"scheduled_task_id": "task-1"}
    assert result == {"run_id": "run-1", "thread_id": "thread-scheduled"}


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_build_run_config_with_context():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"user_id": "u-42", "thread_id": "thread-1"}},
        None,
    )
    assert "context" in config
    assert config["context"]["user_id"] == "u-42"
    assert config["context"]["thread_id"] == "thread-1"
    # 说明当前测试分支所验证的真实行为与边界。
    assert config["configurable"] == {"thread_id": "thread-1"}
    assert config["recursion_limit"] == 100


def test_build_run_config_context_injects_thread_id():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "T-deadbeef-42",
        {"context": {"user_id": "u-1", "thinking_enabled": True}},
        None,
    )

    assert config["context"]["user_id"] == "u-1"
    assert config["context"]["thinking_enabled"] is True
    assert config["context"]["thread_id"] == "T-deadbeef-42"
    assert config["configurable"] == {"thread_id": "T-deadbeef-42"}


def test_build_run_config_null_context_becomes_empty_context():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"context": None}, None)

    assert config["context"] == {"thread_id": "thread-1"}
    assert config["configurable"] == {"thread_id": "thread-1"}


def test_build_run_config_rejects_non_mapping_context():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import pytest

    from app.gateway.services import build_run_config

    with pytest.raises(ValueError, match="context"):
        build_run_config("thread-1", {"context": "bad-context"}, None)


def test_build_run_config_null_context_custom_agent_injects_agent_name():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"context": None}, None, assistant_id="finalis")

    assert config["context"]["agent_name"] == "finalis"
    assert config["configurable"]["agent_name"] == "finalis"


def test_build_run_config_context_plus_configurable_warns(caplog):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import logging

    from app.gateway.services import build_run_config

    with caplog.at_level(logging.WARNING, logger="app.gateway.services"):
        config = build_run_config(
            "thread-1",
            {
                "context": {"user_id": "u-42"},
                "configurable": {"model_name": "gpt-4"},
            },
            None,
        )
    assert "context" in config
    assert config["context"]["user_id"] == "u-42"
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert config["configurable"] == {"thread_id": "thread-1"}
    assert "model_name" not in config["configurable"]
    assert any("both 'context' and 'configurable'" in r.message for r in caplog.records)


def test_build_run_config_context_passthrough_other_keys():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"thread_id": "thread-1"}, "tags": ["prod"]},
        None,
    )
    assert config["context"]["thread_id"] == "thread-1"
    assert config["configurable"] == {"thread_id": "thread-1"}
    assert config["tags"] == ["prod"]


def test_build_run_config_no_request_config():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-abc", None, None)
    assert config["configurable"] == {"thread_id": "thread-abc"}
    assert "context" not in config


def test_strip_internal_context_keys_scrubs_config_smuggled_non_interactive():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from app.gateway.services import build_run_config, strip_internal_context_keys

    via_context = build_run_config("thread-1", {"context": {"non_interactive": True, "model_name": "gpt"}}, None)
    strip_internal_context_keys(via_context)
    assert "non_interactive" not in via_context["context"]
    assert via_context["context"]["model_name"] == "gpt"

    via_configurable = build_run_config("thread-1", {"configurable": {"non_interactive": True}}, None)
    strip_internal_context_keys(via_configurable)
    assert "non_interactive" not in via_configurable["configurable"]
