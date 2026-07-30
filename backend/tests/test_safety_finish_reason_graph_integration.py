'未说明'

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

_TOOL_INVOCATIONS: list[dict[str, Any]] = []


@tool
def write_file(path: str, content: str) -> str:
    """处理写入 文件相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
    _TOOL_INVOCATIONS.append({"path": path, "content": content})
    return f"wrote {len(content)} bytes to {path}"


class _ContentFilteredModel(BaseChatModel):
    '未说明'

    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        '未说明'
        return "fake-content-filtered"

    def bind_tools(self, tools, **kwargs):
        # create_agent binds tools onto the model; we don't actually need
        # to bind anything since responses are hard-coded, but the method
        # must not raise.
        '未说明'
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        '未说明'
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                content="Here is the report:\n# Weekly Politics\n- Meeting time: 2026-05-12—",
                tool_calls=[
                    {
                        "id": "call_truncated_1",
                        "name": "write_file",
                        "args": {
                            "path": "/mnt/user-data/outputs/report.md",
                            "content": "# Weekly Politics\n- Meeting time: 2026-05-12—",
                        },
                    }
                ],
                response_metadata={"finish_reason": "content_filter", "model_name": "fake-kimi"},
            )
        else:
            message = AIMessage(content="ack", response_metadata={"finish_reason": "stop"})
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        '未说明'
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _InspectMiddleware(AgentMiddleware):
    '未说明'

    def __init__(self) -> None:
        '未说明'
        super().__init__()
        self.observed: list[list[Any]] = []

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        """处理模型相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        self.observed.append(list(request.messages))
        return handler(request)


def test_content_filter_with_tool_calls_does_not_invoke_tool_node():
    '未说明'
    _TOOL_INVOCATIONS.clear()
    inspector = _InspectMiddleware()

    agent = create_agent(
        model=_ContentFilteredModel(),
        tools=[write_file],
        # Inspector first so its after_model is registered; Safety last in
        # the list so it executes first under LIFO (matches production wiring).
        middleware=[inspector, SafetyFinishReasonMiddleware()],
    )

    result = agent.invoke({"messages": [HumanMessage(content="write me a report")]})

    # Critical assertion: the dangerous truncated tool call must NOT have
    # been executed. This is the entire point of the middleware.
    assert _TOOL_INVOCATIONS == [], f"write_file was invoked despite content_filter: {_TOOL_INVOCATIONS}"

    # Final AIMessage has no tool calls left.
    final_ai = next(m for m in reversed(result["messages"]) if isinstance(m, AIMessage))
    assert final_ai.tool_calls == []

    # Observability stamp is present.
    record = final_ai.additional_kwargs.get("safety_termination")
    assert record is not None
    assert record["detector"] == "openai_compatible_content_filter"
    assert record["reason_field"] == "finish_reason"
    assert record["reason_value"] == "content_filter"
    assert record["suppressed_tool_call_count"] == 1
    assert record["suppressed_tool_call_names"] == ["write_file"]

    # User-facing explanation is appended.
    assert "safety-related signal" in final_ai.content
    # Original partial text preserved (we don't throw away what the user
    # already saw in the stream — see middleware docstring).
    assert "Weekly Politics" in final_ai.content

    # finish_reason on response_metadata is preserved (so SSE / converters
    # downstream still see the real provider reason).
    assert final_ai.response_metadata.get("finish_reason") == "content_filter"


def test_content_filter_without_tool_calls_passes_through_unchanged():
    '未说明'
    _TOOL_INVOCATIONS.clear()

    class _NoToolModel(BaseChatModel):
        '未说明'
        @property
        def _llm_type(self) -> str:
            '未说明'
            return "fake-no-tool"

        def bind_tools(self, tools, **kwargs):
            '未说明'
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            '未说明'
            msg = AIMessage(
                content="Partial answer truncated by safety filter",
                response_metadata={"finish_reason": "content_filter"},
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            '未说明'
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    agent = create_agent(
        model=_NoToolModel(),
        tools=[write_file],
        middleware=[SafetyFinishReasonMiddleware()],
    )
    result = agent.invoke({"messages": [HumanMessage(content="hi")]})
    final_ai = next(m for m in reversed(result["messages"]) if isinstance(m, AIMessage))

    # Content untouched.
    assert final_ai.content == "Partial answer truncated by safety filter"
    # No safety_termination stamp because we didn't intervene.
    assert "safety_termination" not in final_ai.additional_kwargs
    # tool node never ran (there were no tool calls in the first place).
    assert _TOOL_INVOCATIONS == []


def test_normal_tool_call_round_trip_is_not_affected():
    '未说明'
    _TOOL_INVOCATIONS.clear()

    class _HealthyToolModel(BaseChatModel):
        '未说明'
        call_count: int = 0

        @property
        def _llm_type(self) -> str:
            '未说明'
            return "fake-healthy"

        def bind_tools(self, tools, **kwargs):
            '未说明'
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            '未说明'
            self.call_count += 1
            if self.call_count == 1:
                msg = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_ok",
                            "name": "write_file",
                            "args": {"path": "/tmp/ok", "content": "complete content"},
                        }
                    ],
                    response_metadata={"finish_reason": "tool_calls"},
                )
            else:
                msg = AIMessage(content="done", response_metadata={"finish_reason": "stop"})
            return ChatResult(generations=[ChatGeneration(message=msg)])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            '未说明'
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    agent = create_agent(
        model=_HealthyToolModel(),
        tools=[write_file],
        middleware=[SafetyFinishReasonMiddleware()],
    )
    agent.invoke({"messages": [HumanMessage(content="write")]})

    assert _TOOL_INVOCATIONS == [{"path": "/tmp/ok", "content": "complete content"}]
