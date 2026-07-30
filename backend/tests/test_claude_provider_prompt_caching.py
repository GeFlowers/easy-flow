'定义 test_claude_provider_prompt_caching 模块提供的职责与可复用接口。\n\nTests for ClaudeChatModel._apply_prompt_caching.\n\nValidates that the function never places more than 4 cache_control breakpoints\n(the hard limit enforced by the Anthropic API and AWS Bedrock) regardless of\nhow many system blocks, message content blocks, or tool definitions are present.\n'

from unittest import mock

import pytest

from deerflow.models.claude_provider import ClaudeChatModel


def _make_model(prompt_cache_size: int = 3) -> ClaudeChatModel:
    '执行 _make_model 的明确职责，并返回与调用约定一致的结果。\n\nReturn a minimal ClaudeChatModel instance without network calls.'
    with mock.patch.object(ClaudeChatModel, "model_post_init"):
        m = ClaudeChatModel(
            model="claude-sonnet-4-6",
            anthropic_api_key="sk-ant-fake",  # type: ignore[call-arg]
            prompt_cache_size=prompt_cache_size,
        )
    m._is_oauth = False
    m.enable_prompt_caching = True
    return m


def _count_cache_control(payload: dict) -> int:
    '执行 _count_cache_control 的明确职责，并返回与调用约定一致的结果。\n\nCount the total number of cache_control markers in a payload.'
    count = 0

    system = payload.get("system", [])
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and "cache_control" in block:
                count += 1

    for msg in payload.get("messages", []):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    count += 1

    for tool in payload.get("tools", []):
        if isinstance(tool, dict) and "cache_control" in tool:
            count += 1

    return count


@pytest.fixture()
def model() -> ClaudeChatModel:
    '执行 model 的明确职责，并返回与调用约定一致的结果'
    return _make_model()


# ---------------------------------------------------------------------------
# 基本正确性
# ---------------------------------------------------------------------------


def test_single_system_block_gets_cached(model):
    '验证 single、system、block、gets、cached 场景下的预期行为、边界条件与结果'
    payload: dict = {"system": [{"type": "text", "text": "sys"}]}
    model._apply_prompt_caching(payload)
    assert payload["system"][0].get("cache_control") == {"type": "ephemeral"}


def test_string_system_converted_and_cached(model):
    '验证 string、system、converted、and、cached 场景下的预期行为、边界条件与结果'
    payload: dict = {"system": "you are helpful"}
    model._apply_prompt_caching(payload)
    assert isinstance(payload["system"], list)
    assert payload["system"][0].get("cache_control") == {"type": "ephemeral"}


def test_last_tool_gets_cached_when_budget_allows(model):
    '验证 last、tool、gets、cached、when、budget、allows 场景下的预期行为、边界条件与结果'
    payload: dict = {
        "tools": [{"name": "t1"}, {"name": "t2"}],
    }
    model._apply_prompt_caching(payload)
    # 在没有系统或消息的情况下，应缓存最后一个工具。
    assert payload["tools"][-1].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in payload["tools"][0]


def test_recent_messages_get_cached(model):
    "验证 recent、messages、get、cached 场景下的预期行为、边界条件与结果。\n\nThe last prompt_cache_size messages' content blocks should be cached."
    payload: dict = {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ],
    }
    model._apply_prompt_caching(payload)
    assert payload["messages"][0]["content"][0].get("cache_control") == {"type": "ephemeral"}


def test_string_message_content_converted_and_cached(model):
    '验证 string、message、content、converted、and、cached 场景下的预期行为、边界条件与结果'
    payload: dict = {
        "messages": [
            {"role": "user", "content": "simple string"},
        ],
    }
    model._apply_prompt_caching(payload)
    assert isinstance(payload["messages"][0]["content"], list)
    assert payload["messages"][0]["content"][0].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# 预算执行（问题 #2448 的核心回归测试）
# ---------------------------------------------------------------------------


def test_never_exceeds_4_breakpoints_with_large_system(model):
    '验证 never、exceeds、4、breakpoints、with、large、system 场景下的预期行为、边界条件与结果。\n\nMany system text blocks must not produce more than 4 breakpoints total.'
    payload: dict = {
        "system": [{"type": "text", "text": f"sys {i}"} for i in range(6)],
        "tools": [{"name": "t1"}],
    }
    model._apply_prompt_caching(payload)
    assert _count_cache_control(payload) <= 4


def test_never_exceeds_4_breakpoints_multi_turn_with_multi_block_messages(model):
    '验证 never、exceeds、4、breakpoints、multi、turn、with、multi、block、messages 场景下的预期行为、边界条件与结果。\n\nMulti-turn conversation where each message has multiple content blocks.'
    # 1 个系统块 + 3 条消息 × 2 个块 + 1 个工具 = 8 个候选者 → 上限为 4
    payload: dict = {
        "system": [{"type": "text", "text": "system prompt"}],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "user text"},
                    {"type": "tool_result", "tool_use_id": "x", "content": "result"},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "assistant text"},
                    {"type": "tool_use", "id": "y", "name": "bash", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "follow up"},
                    {"type": "text", "text": "second block"},
                ],
            },
        ],
        "tools": [{"name": "bash"}],
    }
    model._apply_prompt_caching(payload)
    total = _count_cache_control(payload)
    assert total <= 4, f"Expected ≤ 4 breakpoints, got {total}"


def test_never_exceeds_4_breakpoints_many_messages(model):
    '验证 never、exceeds、4、breakpoints、many、messages 场景下的预期行为、边界条件与结果。\n\nLarge number of messages with multiple blocks per message.'
    messages = []
    for i in range(10):
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"msg {i} block a"},
                    {"type": "text", "text": f"msg {i} block b"},
                ],
            }
        )
    payload: dict = {
        "system": [{"type": "text", "text": "sys 1"}, {"type": "text", "text": "sys 2"}],
        "messages": messages,
        "tools": [{"name": "tool_a"}, {"name": "tool_b"}],
    }
    model._apply_prompt_caching(payload)
    total = _count_cache_control(payload)
    assert total <= 4, f"Expected ≤ 4 breakpoints, got {total}"


def test_exactly_4_breakpoints_when_4_or_more_candidates(model):
    '验证 exactly、4、breakpoints、when、4、or、more、candidates 场景下的预期行为、边界条件与结果。\n\nWhen there are at least 4 candidates, exactly 4 breakpoints are placed.'
    payload: dict = {
        "system": [{"type": "text", "text": f"sys {i}"} for i in range(3)],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "user"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "asst"}]},
            {"role": "user", "content": [{"type": "text", "text": "follow"}]},
        ],
        "tools": [{"name": "bash"}],
    }
    model._apply_prompt_caching(payload)
    total = _count_cache_control(payload)
    assert total == 4


def test_breakpoints_placed_on_last_candidates(model):
    '验证 breakpoints、placed、on、last、candidates 场景下的预期行为、边界条件与结果。\n\nBreakpoints should be on the *last* candidates, not the first.'
    # 5 system blocks but budget = 4 → first system block should NOT be cached,
    # 5 个系统块，但预算 = 4 → 第一个系统块不应被缓存，
    payload: dict = {
        "system": [{"type": "text", "text": f"sys {i}"} for i in range(5)],
    }
    model._apply_prompt_caching(payload)
    # 第一个块不在最后 4 个窗口中
    assert "cache_control" not in payload["system"][0]
    # 最后 4 个块被缓存
    for i in range(1, 5):
        assert payload["system"][i].get("cache_control") == {"type": "ephemeral"}, f"block {i} should be cached"


# ---------------------------------------------------------------------------
# 边缘情况
# ---------------------------------------------------------------------------


def test_no_candidates_is_a_no_op(model):
    '验证 no、candidates、is、a、no、op 场景下的预期行为、边界条件与结果'
    payload: dict = {}
    model._apply_prompt_caching(payload)
    assert _count_cache_control(payload) == 0


def test_non_text_system_blocks_not_added_as_candidates(model):
    '验证 non、text、system、blocks、not、added、as、candidates 场景下的预期行为、边界条件与结果。\n\nImage blocks in system should not receive cache_control.'
    payload: dict = {
        "system": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
            {"type": "text", "text": "text block"},
        ],
    }
    model._apply_prompt_caching(payload)
    assert "cache_control" not in payload["system"][0]
    assert payload["system"][1].get("cache_control") == {"type": "ephemeral"}


def test_old_messages_outside_cache_window_not_cached(model):
    '验证 old、messages、outside、cache、window、not、cached 场景下的预期行为、边界条件与结果。\n\nMessages older than prompt_cache_size should not be cached.'
    m = _make_model(prompt_cache_size=1)
    payload: dict = {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "old message"}]},
            {"role": "user", "content": [{"type": "text", "text": "recent message"}]},
        ],
    }
    m._apply_prompt_caching(payload)
    # 只有最后一条消息应该位于缓存窗口内
    assert "cache_control" not in payload["messages"][0]["content"][0]
    assert payload["messages"][1]["content"][0].get("cache_control") == {"type": "ephemeral"}
