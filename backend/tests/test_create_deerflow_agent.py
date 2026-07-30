'定义 test_create_deerflow_agent 模块提供的职责与可复用接口。\n\nTests for create_deerflow_agent SDK entry point.'

from typing import get_type_hints
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.factory import create_deerflow_agent
from deerflow.agents.features import Next, Prev, RuntimeFeatures
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.agents.thread_state import ThreadState


def _make_mock_model():
    '执行 _make_mock_model 的明确职责，并返回与调用约定一致的结果'
    return MagicMock(name="mock_model")


def _make_mock_tool(name: str = "my_tool"):
    '执行 _make_mock_tool 的明确职责，并返回与调用约定一致的结果'
    tool = MagicMock(name=name)
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# 1. 最小化创建——仅模型
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_minimal_creation(mock_create_agent):
    '验证 minimal、creation 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock(name="compiled_graph")
    model = _make_mock_model()

    result = create_deerflow_agent(model)

    mock_create_agent.assert_called_once()
    assert result is mock_create_agent.return_value
    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["model"] is model
    assert call_kwargs["system_prompt"] is None


# ---------------------------------------------------------------------------
# 2. 使用工具
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_with_tools(mock_create_agent):
    '验证 with、tools 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    model = _make_mock_model()
    tool = _make_mock_tool("search")

    create_deerflow_agent(model, tools=[tool])

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "search" in tool_names


# ---------------------------------------------------------------------------
# 3. 使用 system_prompt
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_with_system_prompt(mock_create_agent):
    '验证 with、system、prompt 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    prompt = "You are a helpful assistant."

    create_deerflow_agent(_make_mock_model(), system_prompt=prompt)

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["system_prompt"] == prompt


# ---------------------------------------------------------------------------
# 4. 特性模式——自动组装中间件链
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_features_mode(mock_create_agent):
    '验证 features、mode 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(sandbox=True, auto_title=True)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert len(middleware) > 0
    mw_types = [type(m).__name__ for m in middleware]
    assert "ThreadDataMiddleware" in mw_types
    assert "SandboxMiddleware" in mw_types
    assert "TitleMiddleware" in mw_types
    assert "ClarificationMiddleware" in mw_types


# ---------------------------------------------------------------------------
# 5.中间件全面接管
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_middleware_takeover(mock_create_agent):
    '验证 middleware、takeover 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    custom_mw = MagicMock(name="custom_middleware")
    custom_mw.name = "custom"

    create_deerflow_agent(_make_mock_model(), middleware=[custom_mw])

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["middleware"] == [custom_mw]


# ---------------------------------------------------------------------------
# 6. 冲突 — 中间件 + 功能引发 ValueError
# ---------------------------------------------------------------------------
def test_middleware_and_features_conflict():
    '验证 middleware、and、features、conflict 场景下的预期行为、边界条件与结果'
    with pytest.raises(ValueError, match="Cannot specify both"):
        create_deerflow_agent(
            _make_mock_model(),
            middleware=[MagicMock()],
            features=RuntimeFeatures(),
        )


# ---------------------------------------------------------------------------
# 7. 当线程数据可用时，视觉功能自动注入 view_image_tool
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_vision_injects_view_image_tool(mock_create_agent):
    '验证 vision、injects、view、image、tool 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(vision=True, sandbox=True)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "view_image" in tool_names


@patch("deerflow.agents.factory.create_agent")
def test_vision_without_sandbox_does_not_inject_view_image_tool(mock_create_agent):
    '验证 vision、without、sandbox、does、not、inject、view、image、tool 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(vision=True, sandbox=False)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "view_image" not in tool_names


def test_view_image_middleware_preserves_viewed_images_reducer():
    '验证 view、image、middleware、preserves、viewed、images、reducer 场景下的预期行为、边界条件与结果'
    middleware_hints = get_type_hints(ViewImageMiddleware.state_schema, include_extras=True)
    thread_hints = get_type_hints(ThreadState, include_extras=True)

    assert middleware_hints["viewed_images"] == thread_hints["viewed_images"]


# ---------------------------------------------------------------------------
# 8.子代理功能自动注入task_tool
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_subagent_injects_task_tool(mock_create_agent):
    '验证 subagent、injects、task、tool 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(subagent=True, sandbox=False)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "task" in tool_names


# ---------------------------------------------------------------------------
# 9. 中间件排序 — ClarificationMiddleware 始终位于最后
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_clarification_always_last(mock_create_agent):
    '验证 clarification、always、last 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(sandbox=True, memory=True, vision=True)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    last_mw = middleware[-1]
    assert type(last_mw).__name__ == "ClarificationMiddleware"


# ---------------------------------------------------------------------------
# 10. RuntimeFeatures 默认值
# ---------------------------------------------------------------------------
def test_agent_features_defaults():
    '验证 agent、features、defaults 场景下的预期行为、边界条件与结果'
    f = RuntimeFeatures()
    assert f.sandbox is True
    assert f.memory is False
    assert f.summarization is False
    assert f.subagent is False
    assert f.vision is False
    assert f.auto_title is False
    assert f.guardrail is False
    assert f.loop_detection is True


# ---------------------------------------------------------------------------
# 11.工具重复数据删除——用户提供的工具优先
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_tool_deduplication(mock_create_agent):
    '验证 tool、deduplication 场景下的预期行为、边界条件与结果。\n\nIf user provides a tool with the same name as an auto-injected one, no duplicate.'
    mock_create_agent.return_value = MagicMock()
    user_clarification = _make_mock_tool("ask_clarification")

    create_deerflow_agent(_make_mock_model(), tools=[user_clarification], features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    names = [t.name for t in call_kwargs["tools"]]
    assert names.count("ask_clarification") == 1
    # 第一个应该是用户提供的工具
    assert call_kwargs["tools"][0] is user_clarification


# ---------------------------------------------------------------------------
# 12. 沙箱已禁用 — 无 ThreadData/Uploads/Sandbox 中间件
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_sandbox_disabled(mock_create_agent):
    '验证 sandbox、disabled 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(sandbox=False)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "ThreadDataMiddleware" not in mw_types
    assert "UploadsMiddleware" not in mw_types
    assert "SandboxMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 13. 检查点通过
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_checkpointer_passthrough(mock_create_agent):
    '验证 checkpointer、passthrough 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    cp = MagicMock(name="checkpointer")

    create_deerflow_agent(_make_mock_model(), checkpointer=cp)

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["checkpointer"] is cp


# ---------------------------------------------------------------------------
# 14.自定义AgentMiddleware实例替换默认实例
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_custom_middleware_replaces_default(mock_create_agent):
    '验证 custom、middleware、replaces、default 场景下的预期行为、边界条件与结果。\n\nPassing an AgentMiddleware instance uses it directly instead of the built-in default.'
    from langchain.agents.middleware import AgentMiddleware

    mock_create_agent.return_value = MagicMock()

    class MyMemoryMiddleware(AgentMiddleware):
        '封装 MyMemoryMiddleware 的状态、协作关系与公开操作'
        pass

    custom_memory = MyMemoryMiddleware()
    feat = RuntimeFeatures(sandbox=False, memory=custom_memory)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert custom_memory in middleware
    # 不应该有默认的 MemoryMiddleware
    mw_types = [type(m).__name__ for m in middleware]
    assert "MemoryMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 15.自定义沙箱中间件替换3-中间件组
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_custom_sandbox_replaces_group(mock_create_agent):
    '验证 custom、sandbox、replaces、group 场景下的预期行为、边界条件与结果。\n\nPassing an AgentMiddleware for sandbox replaces ThreadData+Uploads+Sandbox with one.'
    from langchain.agents.middleware import AgentMiddleware

    mock_create_agent.return_value = MagicMock()

    class MySandbox(AgentMiddleware):
        '封装 MySandbox 的状态、协作关系与公开操作'
        pass

    custom_sb = MySandbox()
    feat = RuntimeFeatures(sandbox=custom_sb)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert custom_sb in middleware
    mw_types = [type(m).__name__ for m in middleware]
    assert "ThreadDataMiddleware" not in mw_types
    assert "UploadsMiddleware" not in mw_types
    assert "SandboxMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 16. 存在始终在线的错误处理中间件
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_always_on_error_handling(mock_create_agent):
    '验证 always、on、error、handling 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(sandbox=False)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    assert "DanglingToolCallMiddleware" in mw_types
    assert "ToolErrorHandlingMiddleware" in mw_types
    tool_error_middleware = next(m for m in middleware if type(m).__name__ == "ToolErrorHandlingMiddleware")
    assert tool_error_middleware._app_config is None


# ---------------------------------------------------------------------------
# 17. 自定义中间件的愿景遵循线程数据可用性
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_vision_custom_middleware_without_sandbox_does_not_inject_tool(mock_create_agent):
    '验证 vision、custom、middleware、without、sandbox、does、not、inject、tool 场景下的预期行为、边界条件与结果。\n\nCustom vision middleware without thread data does not get view_image_tool auto-injected.'
    from langchain.agents.middleware import AgentMiddleware

    mock_create_agent.return_value = MagicMock()

    class MyVision(AgentMiddleware):
        '封装 MyVision 的状态、协作关系与公开操作'
        pass

    feat = RuntimeFeatures(sandbox=False, vision=MyVision())

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "view_image" not in tool_names


# ===========================================================================
# @Next / @Prev 装饰器和 extra_middleware 插入
# ===========================================================================


# ---------------------------------------------------------------------------
# 18.@Next 装饰器设置 _next_anchor
# ---------------------------------------------------------------------------
def test_next_decorator():
    '验证 next、decorator 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    class Anchor(AgentMiddleware):
        '封装 Anchor 的状态、协作关系与公开操作'
        pass

    @Next(Anchor)
    class MyMW(AgentMiddleware):
        '封装 MyMW 的状态、协作关系与公开操作'
        pass

    assert MyMW._next_anchor is Anchor


# ---------------------------------------------------------------------------
# 19. @Prev 装饰器设置 _prev_anchor
# ---------------------------------------------------------------------------
def test_prev_decorator():
    '验证 prev、decorator 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    class Anchor(AgentMiddleware):
        '封装 Anchor 的状态、协作关系与公开操作'
        pass

    @Prev(Anchor)
    class MyMW(AgentMiddleware):
        '封装 MyMW 的状态、协作关系与公开操作'
        pass

    assert MyMW._prev_anchor is Anchor


# ---------------------------------------------------------------------------
# 20.带有@Next的extra_middleware在锚点后插入
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_extra_next_inserts_after_anchor(mock_create_agent):
    '验证 extra、next、inserts、after、anchor 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    mock_create_agent.return_value = MagicMock()

    @Next(DanglingToolCallMiddleware)
    class MyAudit(AgentMiddleware):
        '封装 MyAudit 的状态、协作关系与公开操作'
        pass

    audit = MyAudit()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[audit],
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    dangling_idx = mw_types.index("DanglingToolCallMiddleware")
    audit_idx = mw_types.index("MyAudit")
    assert audit_idx == dangling_idx + 1


# ---------------------------------------------------------------------------
# 21.带有@Prev的extra_middleware在锚点之前插入
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_extra_prev_inserts_before_anchor(mock_create_agent):
    '验证 extra、prev、inserts、before、anchor 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    mock_create_agent.return_value = MagicMock()

    @Prev(ClarificationMiddleware)
    class MyFilter(AgentMiddleware):
        '封装 MyFilter 的状态、协作关系与公开操作'
        pass

    filt = MyFilter()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[filt],
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    clar_idx = mw_types.index("ClarificationMiddleware")
    filt_idx = mw_types.index("MyFilter")
    assert filt_idx == clar_idx - 1


# ---------------------------------------------------------------------------
# 22. 未锚定的 extra_middleware 位于 ClarificationMiddleware 之前
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_extra_unanchored_before_clarification(mock_create_agent):
    '验证 extra、unanchored、before、clarification 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    mock_create_agent.return_value = MagicMock()

    class MyPlain(AgentMiddleware):
        '封装 MyPlain 的状态、协作关系与公开操作'
        pass

    plain = MyPlain()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[plain],
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    assert mw_types[-1] == "ClarificationMiddleware"
    assert mw_types[-2] == "MyPlain"


# ---------------------------------------------------------------------------
# 23. 冲突：两个额外的 @Next 相同的锚 → ValueError
# ---------------------------------------------------------------------------
def test_extra_conflict_same_next_target():
    '验证 extra、conflict、same、next、target 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    @Next(DanglingToolCallMiddleware)
    class MW1(AgentMiddleware):
        '封装 MW1 的状态、协作关系与公开操作'
        pass

    @Next(DanglingToolCallMiddleware)
    class MW2(AgentMiddleware):
        '封装 MW2 的状态、协作关系与公开操作'
        pass

    with pytest.raises(ValueError, match="Conflict"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW1(), MW2()],
        )


# ---------------------------------------------------------------------------
# 24. 冲突：两个额外的 @Prev 相同的锚 → ValueError
# ---------------------------------------------------------------------------
def test_extra_conflict_same_prev_target():
    '验证 extra、conflict、same、prev、target 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    @Prev(ClarificationMiddleware)
    class MW1(AgentMiddleware):
        '封装 MW1 的状态、协作关系与公开操作'
        pass

    @Prev(ClarificationMiddleware)
    class MW2(AgentMiddleware):
        '封装 MW2 的状态、协作关系与公开操作'
        pass

    with pytest.raises(ValueError, match="Conflict"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW1(), MW2()],
        )


# ---------------------------------------------------------------------------
# 25. @Next 和 @Prev 都在同一个类上 → ValueError
# ---------------------------------------------------------------------------
def test_extra_both_next_and_prev_error():
    '验证 extra、both、next、and、prev、error 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    class MW(AgentMiddleware):
        '封装 MW 的状态、协作关系与公开操作'
        pass

    MW._next_anchor = DanglingToolCallMiddleware
    MW._prev_anchor = ClarificationMiddleware

    with pytest.raises(ValueError, match="both @Next and @Prev"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW()],
        )


# ---------------------------------------------------------------------------
# 26. 交叉外部锚定：额外的锚点到另一个额外的锚点
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_extra_cross_external_anchoring(mock_create_agent):
    '验证 extra、cross、external、anchoring 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    mock_create_agent.return_value = MagicMock()

    @Next(DanglingToolCallMiddleware)
    class First(AgentMiddleware):
        '封装 First 的状态、协作关系与公开操作'
        pass

    @Next(First)
    class Second(AgentMiddleware):
        '封装 Second 的状态、协作关系与公开操作'
        pass

    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[Second(), First()],  # intentionally reversed
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    dangling_idx = mw_types.index("DanglingToolCallMiddleware")
    first_idx = mw_types.index("First")
    second_idx = mw_types.index("Second")
    assert first_idx == dangling_idx + 1
    assert second_idx == first_idx + 1


# ---------------------------------------------------------------------------
# 27. 无法解析的锚 → ValueError
# ---------------------------------------------------------------------------
def test_extra_unresolvable_anchor():
    '验证 extra、unresolvable、anchor 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    class Ghost(AgentMiddleware):
        '封装 Ghost 的状态、协作关系与公开操作'
        pass

    @Next(Ghost)
    class MW(AgentMiddleware):
        '封装 MW 的状态、协作关系与公开操作'
        pass

    with pytest.raises(ValueError, match="Cannot resolve"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW()],
        )


# ---------------------------------------------------------------------------
# 28. extra_middleware + 中间件（完全接管）→ ValueError
# ---------------------------------------------------------------------------
def test_extra_with_middleware_takeover_conflict():
    '验证 extra、with、middleware、takeover、conflict 场景下的预期行为、边界条件与结果'
    with pytest.raises(ValueError, match="full takeover"):
        create_deerflow_agent(
            _make_mock_model(),
            middleware=[MagicMock()],
            extra_middleware=[MagicMock()],
        )


# ===========================================================================
# LoopDetection、TodoMiddleware、GuardrailMiddleware
# ===========================================================================


# ---------------------------------------------------------------------------
# 29. LoopDetectionMiddleware 始终存在
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_loop_detection_always_present(mock_create_agent):
    '验证 loop、detection、always、present 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "LoopDetectionMiddleware" in mw_types


# ---------------------------------------------------------------------------
# 30. 澄清之前的 LoopDetection
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_loop_detection_before_clarification(mock_create_agent):
    '验证 loop、detection、before、clarification 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    loop_idx = mw_types.index("LoopDetectionMiddleware")
    clar_idx = mw_types.index("ClarificationMiddleware")
    assert loop_idx < clar_idx
    assert loop_idx == clar_idx - 1


# ---------------------------------------------------------------------------
# 30b。 Loop_Detection=False 跳过 LoopDetectionMiddleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_loop_detection_disabled(mock_create_agent):
    '验证 loop、detection、disabled 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False, loop_detection=False),
    )

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "LoopDetectionMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 30c。 Loop_Detection=<自定义AgentMiddleware>替换默认的
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_loop_detection_custom_middleware(mock_create_agent):
    '验证 loop、detection、custom、middleware 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware as AM

    mock_create_agent.return_value = MagicMock()

    class MyLoopDetection(AM):
        '封装 MyLoopDetection 的状态、协作关系与公开操作'
        pass

    custom = MyLoopDetection()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False, loop_detection=custom),
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert custom in middleware
    mw_types = [type(m).__name__ for m in middleware]
    # 默认 LoopDetectionMiddleware 也不得出现。
    assert "LoopDetectionMiddleware" not in mw_types
    # 自定义替换位于 TokenBudgetMiddleware 和 ClarificationMiddleware 之前。
    assert mw_types[-1] == "ClarificationMiddleware"
    assert mw_types[-2] == "MyLoopDetection"


# ---------------------------------------------------------------------------
# 31. plan_mode=True 添加 TodoMiddleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_plan_mode_adds_todo_middleware(mock_create_agent):
    '验证 plan、mode、adds、todo、middleware 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False), plan_mode=True)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "TodoMiddleware" in mw_types


# ---------------------------------------------------------------------------
# 32. plan_mode=False（默认）— 无 TodoMiddleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_plan_mode_default_no_todo(mock_create_agent):
    '验证 plan、mode、default、no、todo 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "TodoMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 33. 摘要=没有模型的 True → ValueError
# ---------------------------------------------------------------------------
def test_summarization_true_raises():
    '验证 summarization、true、raises 场景下的预期行为、边界条件与结果'
    with pytest.raises(ValueError, match="requires a custom AgentMiddleware"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False, summarization=True),
        )


# ---------------------------------------------------------------------------
# 34.guardrail=True 不带内置 → ValueError
# ---------------------------------------------------------------------------
def test_guardrail_true_raises():
    '验证 guardrail、true、raises 场景下的预期行为、边界条件与结果'
    with pytest.raises(ValueError, match="requires a custom AgentMiddleware"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False, guardrail=True),
        )


# ---------------------------------------------------------------------------
# 34.用自定义AgentMiddleware替换默认的护栏
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_guardrail_custom_middleware(mock_create_agent):
    '验证 guardrail、custom、middleware 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware as AM

    mock_create_agent.return_value = MagicMock()

    class MyGuardrail(AM):
        '封装 MyGuardrail 的状态、协作关系与公开操作'
        pass

    custom = MyGuardrail()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False, guardrail=custom),
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert custom in middleware
    mw_types = [type(m).__name__ for m in middleware]
    assert "GuardrailMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 35.guardrail=False（默认）— 无 GuardrailMiddleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_guardrail_default_off(mock_create_agent):
    '验证 guardrail、default、off 场景下的预期行为、边界条件与结果'
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "GuardrailMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 36. 全链顺序匹配 make_lead_agent （所有功能开启）
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_full_chain_order(mock_create_agent):
    '验证 full、chain、order 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware as AM

    mock_create_agent.return_value = MagicMock()

    class MyGuardrail(AM):
        '封装 MyGuardrail 的状态、协作关系与公开操作'
        pass

    class MySummarization(AM):
        '封装 MySummarization 的状态、协作关系与公开操作'
        pass

    feat = RuntimeFeatures(
        sandbox=True,
        memory=True,
        summarization=MySummarization(),
        subagent=True,
        vision=True,
        auto_title=True,
        guardrail=MyGuardrail(),
    )
    create_deerflow_agent(_make_mock_model(), features=feat, plan_mode=True)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]

    expected_order = [
        "ThreadDataMiddleware",
        "UploadsMiddleware",
        "SandboxMiddleware",
        "DanglingToolCallMiddleware",
        "MyGuardrail",
        "ToolErrorHandlingMiddleware",
        "MySummarization",
        "TodoMiddleware",
        "TitleMiddleware",
        "MemoryMiddleware",
        "ViewImageMiddleware",
        "SubagentLimitMiddleware",
        "LoopDetectionMiddleware",
        "ClarificationMiddleware",
    ]
    assert mw_types == expected_order


# ---------------------------------------------------------------------------
# 37. @Next(ClarificationMiddleware) 不会破坏尾部不变式
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_next_clarification_preserves_tail_invariant(mock_create_agent):
    '验证 next、clarification、preserves、tail、invariant 场景下的预期行为、边界条件与结果。\n\nEven with @Next(ClarificationMiddleware), Clarification stays last.'
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    mock_create_agent.return_value = MagicMock()

    @Next(ClarificationMiddleware)
    class AfterClar(AgentMiddleware):
        '封装 AfterClar 的状态、协作关系与公开操作'
        pass

    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[AfterClar()],
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    assert mw_types[-1] == "ClarificationMiddleware"
    assert "AfterClar" in mw_types


# ---------------------------------------------------------------------------
# 38.来自不同额外内容的同一锚点上的 @Next(X) + @Prev(X) → ValueError
# ---------------------------------------------------------------------------
def test_extra_opposite_direction_same_anchor_conflict():
    '验证 extra、opposite、direction、same、anchor、conflict 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    @Next(DanglingToolCallMiddleware)
    class AfterDangling(AgentMiddleware):
        '封装 AfterDangling 的状态、协作关系与公开操作'
        pass

    @Prev(DanglingToolCallMiddleware)
    class BeforeDangling(AgentMiddleware):
        '封装 BeforeDangling 的状态、协作关系与公开操作'
        pass

    with pytest.raises(ValueError, match="cross-anchoring"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[AfterDangling(), BeforeDangling()],
        )


# ===========================================================================
# 输入验证和错误消息强化
# ===========================================================================


# ---------------------------------------------------------------------------
# 39. @Next 带有非 AgentMiddleware 锚 → TypeError
# ---------------------------------------------------------------------------
def test_next_bad_anchor_type():
    '验证 next、bad、anchor、type 场景下的预期行为、边界条件与结果'
    with pytest.raises(TypeError, match="AgentMiddleware subclass"):

        @Next(str)  # type: ignore[arg-type]
        class MW:
            '封装 MW 的状态、协作关系与公开操作'
            pass


# ---------------------------------------------------------------------------
# 40. @Prev 带有非 AgentMiddleware 锚 → TypeError
# ---------------------------------------------------------------------------
def test_prev_bad_anchor_type():
    '验证 prev、bad、anchor、type 场景下的预期行为、边界条件与结果'
    with pytest.raises(TypeError, match="AgentMiddleware subclass"):

        @Prev(42)  # type: ignore[arg-type]
        class MW:
            '封装 MW 的状态、协作关系与公开操作'
            pass


# ---------------------------------------------------------------------------
# 41.带有非 AgentMiddleware 项的 extra_middleware → TypeError
# ---------------------------------------------------------------------------
def test_extra_middleware_bad_type():
    '验证 extra、middleware、bad、type 场景下的预期行为、边界条件与结果'
    with pytest.raises(TypeError, match="AgentMiddleware instances"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[object()],  # type: ignore[list-item]
        )


# ---------------------------------------------------------------------------
# 42. extras 之间的循环依赖 → 清除错误消息
# ---------------------------------------------------------------------------
def test_extra_circular_dependency():
    '验证 extra、circular、dependency 场景下的预期行为、边界条件与结果'
    from langchain.agents.middleware import AgentMiddleware

    class MW_A(AgentMiddleware):
        '封装 MW_A 的状态、协作关系与公开操作'
        pass

    class MW_B(AgentMiddleware):
        '封装 MW_B 的状态、协作关系与公开操作'
        pass

    MW_A._next_anchor = MW_B  # type: ignore[attr-defined]
    MW_B._next_anchor = MW_A  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="Circular dependency"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW_A(), MW_B()],
        )
