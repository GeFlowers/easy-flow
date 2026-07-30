'定义 _agent_e2e_helpers 模块提供的职责与可复用接口。\n\nShared helpers for user-isolation e2e tests on the custom-agent tooling.\n\nCentralises the small fake-LLM shim and a few test-data builders that the\nthree e2e files in this PR (``test_setup_agent_e2e_user_isolation``,\n``test_update_agent_e2e_user_isolation``, ``test_setup_agent_http_e2e_real_server``)\nall need. The shim is what lets a real ``langchain.agents.create_agent``\ngraph run without an API key — every other layer in those tests is real\nproduction code, which is the entire point of the test design.\n'

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable


class FakeToolCallingModel(FakeMessagesListChatModel):
    '封装 FakeToolCallingModel 的状态、协作关系与公开操作。\n\nFakeMessagesListChatModel plus a no-op ``bind_tools`` for create_agent.\n\n    ``langchain.agents.create_agent`` calls ``model.bind_tools(...)`` to\n    expose the tool schemas to the model; the upstream fake raises\n    ``NotImplementedError`` there. We just return ``self`` because we\n    drive deterministic tool_call output via ``responses=...``, no schema\n    handling needed.\n    '

    def bind_tools(  # type: ignore[override]
        self,
        tools: Any,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> Runnable:
        '执行 bind_tools 的明确职责，并返回与调用约定一致的结果'
        return self


def build_single_tool_call_model(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_id: str = "call_e2e_1",
    final_text: str = "done",
) -> FakeToolCallingModel:
    '构建并返回，并遵守 build_single_tool_call_model 所表达的接口约束。\n\nBuild a fake model that emits exactly one tool_call then finishes.\n\n    Two-turn behaviour, identical across our e2e tests:\n      turn 1 → AIMessage with a single tool_call for *tool_name*\n      turn 2 → AIMessage with *final_text* (terminates the agent loop)\n    '
    return FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": tool_name,
                        "args": tool_args,
                        "id": tool_call_id,
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content=final_text),
        ]
    )
