'定义 test_create_deerflow_agent_live 模块提供的职责与可复用接口。\n\nLive integration tests for create_deerflow_agent.\n\nVerifies the factory produces a working LangGraph agent that can actually\nprocess messages end-to-end with a real LLM.\n\nTests marked ``requires_llm`` are skipped in CI or when OPENAI_API_KEY is unset.\n'

import os
import uuid

import pytest
from langchain_core.tools import tool

requires_llm = pytest.mark.skipif(
    os.getenv("CI", "").lower() in ("true", "1") or not os.getenv("OPENAI_API_KEY"),
    reason="Requires LLM API key — skipped in CI or when OPENAI_API_KEY is unset",
)


def _make_model():
    '执行 _make_model 的明确职责，并返回与调用约定一致的结果。\n\nCreate a real chat model from environment variables.'
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=os.getenv("E2E_MODEL_ID", "ep-20251211175242-llcmh"),
        base_url=os.getenv("E2E_BASE_URL", "https://ark-cn-beijing.bytedance.net/api/v3"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        max_tokens=256,
        temperature=0,
    )


# ---------------------------------------------------------------------------
# 1. 最少的创建 — 仅模型，无特征
# ---------------------------------------------------------------------------
@requires_llm
def test_minimal_agent_responds():
    '验证 minimal、agent、responds 场景下的预期行为、边界条件与结果。\n\ncreate_deerflow_agent(model) produces a graph that returns a response.'
    from deerflow.agents.factory import create_deerflow_agent

    model = _make_model()
    graph = create_deerflow_agent(model, features=None, middleware=[])

    result = graph.invoke(
        {"messages": [("user", "Say exactly: pong")]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    messages = result.get("messages", [])
    assert len(messages) >= 2
    last_msg = messages[-1]
    assert hasattr(last_msg, "content")
    assert len(last_msg.content) > 0


# ---------------------------------------------------------------------------
# 2. 使用自定义工具 — 验证工具注入和执行
# ---------------------------------------------------------------------------
@requires_llm
def test_agent_with_custom_tool():
    '验证 agent、with、custom、tool 场景下的预期行为、边界条件与结果。\n\nAgent can invoke a user-provided tool and return the result.'
    from deerflow.agents.factory import create_deerflow_agent

    @tool
    def add(a: int, b: int) -> int:
        '执行 add 的明确职责，并返回与调用约定一致的结果。\n\nAdd two numbers.'
        return a + b

    model = _make_model()
    graph = create_deerflow_agent(model, tools=[add], middleware=[])

    result = graph.invoke(
        {"messages": [("user", "Use the add tool to compute 3 + 7. Return only the result.")]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    messages = result.get("messages", [])
    # 应包含：用户消息、AI tool_call、工具结果、AI 最终结果
    assert len(messages) >= 3
    last_content = messages[-1].content
    assert "10" in last_content


# ---------------------------------------------------------------------------
# 3. RuntimeFeatures模式——中间件链运行无错误
# ---------------------------------------------------------------------------
@requires_llm
def test_features_mode_middleware_chain():
    '验证 features、mode、middleware、chain 场景下的预期行为、边界条件与结果。\n\nRuntimeFeatures assembles a working middleware chain that executes.'
    from deerflow.agents.factory import create_deerflow_agent
    from deerflow.agents.features import RuntimeFeatures

    model = _make_model()
    feat = RuntimeFeatures(sandbox=False, auto_title=False, memory=False)
    graph = create_deerflow_agent(model, features=feat)

    result = graph.invoke(
        {"messages": [("user", "What is 2+2?")]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    messages = result.get("messages", [])
    assert len(messages) >= 2
    last_content = messages[-1].content
    assert len(last_content) > 0
