"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

import copy
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import tool as as_tool
from pydantic import PrivateAttr

from deerflow.agents.middlewares.loop_detection_middleware import (
    _HARD_STOP_MSG,
    _MAX_PENDING_WARNINGS_PER_RUN,
    LoopDetectionMiddleware,
    _hash_tool_calls,
)


def _make_runtime(thread_id="test-thread", run_id="test-run"):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id, "run_id": run_id}
    return runtime


def _pending_key(thread_id="test-thread", run_id="test-run"):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return (thread_id, run_id)


def _make_request(messages, runtime):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    request = MagicMock()
    request.messages = list(messages)
    request.runtime = runtime
    request.override = lambda **updates: _override_request(request, updates)
    return request


def _override_request(request, updates):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    new = MagicMock()
    new.messages = updates.get("messages", request.messages)
    new.runtime = updates.get("runtime", request.runtime)
    new.override = lambda **u: _override_request(new, u)
    return new


def _capture_handler():
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    captured: list = []

    def handler(req):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        captured.append(req)
        return MagicMock()

    return captured, handler


class _CapturingFakeMessagesListChatModel(FakeMessagesListChatModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    _seen_messages: list[list[Any]] = PrivateAttr(default_factory=list)

    @property
    def seen_messages(self) -> list[list[Any]]:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return self._seen_messages

    def bind_tools(
        self,
        tools: Any,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> Runnable:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self._seen_messages.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def _make_state(tool_calls=None, content=""):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    safe_content = copy.deepcopy(content) if isinstance(content, list) else content
    msg = AIMessage(content=safe_content, tool_calls=tool_calls or [])
    return {"messages": [msg]}


def _bash_call(cmd="ls"):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return {"name": "bash", "id": f"call_{cmd}", "args": {"command": cmd}}


class TestHashToolCalls:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_same_calls_same_hash(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        a = _hash_tool_calls([_bash_call("ls")])
        b = _hash_tool_calls([_bash_call("ls")])
        assert a == b

    def test_different_calls_different_hash(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        a = _hash_tool_calls([_bash_call("ls")])
        b = _hash_tool_calls([_bash_call("pwd")])
        assert a != b

    def test_order_independent(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        a = _hash_tool_calls([_bash_call("ls"), {"name": "read_file", "args": {"path": "/tmp"}}])
        b = _hash_tool_calls([{"name": "read_file", "args": {"path": "/tmp"}}, _bash_call("ls")])
        assert a == b

    def test_empty_calls(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        h = _hash_tool_calls([])
        assert isinstance(h, str)
        assert len(h) > 0

    def test_stringified_dict_args_match_dict_args(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        dict_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": "1", "end_line": "150"},
        }
        string_call = {
            "name": "read_file",
            "args": '{"path":"/tmp/demo.py","start_line":"1","end_line":"150"}',
        }

        assert _hash_tool_calls([dict_call]) == _hash_tool_calls([string_call])

    def test_reversed_read_file_range_matches_forward_range(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        forward_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": 10, "end_line": 300},
        }
        reversed_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": 300, "end_line": 10},
        }

        assert _hash_tool_calls([forward_call]) == _hash_tool_calls([reversed_call])

    def test_stringified_non_dict_args_do_not_crash(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        non_dict_json_call = {"name": "bash", "args": '"echo hello"'}
        plain_string_call = {"name": "bash", "args": "echo hello"}

        json_hash = _hash_tool_calls([non_dict_json_call])
        plain_hash = _hash_tool_calls([plain_string_call])

        assert isinstance(json_hash, str)
        assert isinstance(plain_hash, str)
        assert json_hash
        assert plain_hash

    def test_grep_pattern_affects_hash(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        grep_foo = {"name": "grep", "args": {"path": "/tmp", "pattern": "foo"}}
        grep_bar = {"name": "grep", "args": {"path": "/tmp", "pattern": "bar"}}

        assert _hash_tool_calls([grep_foo]) != _hash_tool_calls([grep_bar])

    def test_glob_pattern_affects_hash(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        glob_py = {"name": "glob", "args": {"path": "/tmp", "pattern": "*.py"}}
        glob_ts = {"name": "glob", "args": {"path": "/tmp", "pattern": "*.ts"}}

        assert _hash_tool_calls([glob_py]) != _hash_tool_calls([glob_ts])

    def test_write_file_content_affects_hash(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        v1 = {"name": "write_file", "args": {"path": "/tmp/a.py", "content": "v1"}}
        v2 = {"name": "write_file", "args": {"path": "/tmp/a.py", "content": "v2"}}
        assert _hash_tool_calls([v1]) != _hash_tool_calls([v2])

    def test_str_replace_content_affects_hash(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        a = {
            "name": "str_replace",
            "args": {"path": "/tmp/a.py", "old_str": "foo", "new_str": "bar"},
        }
        b = {
            "name": "str_replace",
            "args": {"path": "/tmp/a.py", "old_str": "foo", "new_str": "baz"},
        }
        assert _hash_tool_calls([a]) != _hash_tool_calls([b])


class TestLoopDetection:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_no_tool_calls_returns_none(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        state = {"messages": [AIMessage(content="hello")]}
        result = mw._apply(state, runtime)
        assert result is None

    def test_below_threshold_returns_none(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for _ in range(2):
            result = mw._apply(_make_state(tool_calls=call), runtime)
            assert result is None

    def test_warn_at_threshold_queues_but_does_not_mutate_state(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(2):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=call), runtime)
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert result is None
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert mw._pending_warnings[_pending_key()]
        assert "LOOP DETECTED" in mw._pending_warnings[_pending_key()][0]

    def test_warn_injected_at_next_model_call(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]
        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        ai_msg = AIMessage(content="", tool_calls=call)
        tool_msg = ToolMessage(content="ok", tool_call_id=call[0]["id"], name="bash")
        request = _make_request([ai_msg, tool_msg], runtime)

        captured, handler = _capture_handler()
        mw.wrap_model_call(request, handler)

        sent = captured[0].messages
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert sent[0] is ai_msg
        assert sent[1] is tool_msg
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert isinstance(sent[2], HumanMessage)
        assert sent[2].name == "loop_warning"
        assert "LOOP DETECTED" in sent[2].content

    def test_warn_queue_drained_after_injection(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]
        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        request = _make_request([AIMessage(content="hi")], runtime)
        captured, handler = _capture_handler()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw.wrap_model_call(request, handler)
        first = captured[0].messages
        assert any(isinstance(m, HumanMessage) for m in first)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        request2 = _make_request([AIMessage(content="hi")], runtime)
        mw.wrap_model_call(request2, handler)
        second = captured[1].messages
        assert not any(isinstance(m, HumanMessage) for m in second)

    def test_warn_queue_scoped_by_run_id(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime_a = _make_runtime(run_id="run-A")
        runtime_b = _make_runtime(run_id="run-B")
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime_a)

        request_b = _make_request([AIMessage(content="hi")], runtime_b)
        captured, handler = _capture_handler()
        mw.wrap_model_call(request_b, handler)
        assert not any(isinstance(m, HumanMessage) for m in captured[0].messages)
        assert mw._pending_warnings.get(_pending_key(run_id="run-A"))

        request_a = _make_request([AIMessage(content="hi")], runtime_a)
        mw.wrap_model_call(request_a, handler)
        assert any(isinstance(message, HumanMessage) and message.name == "loop_warning" for message in captured[1].messages)

    def test_missing_run_id_uses_per_runtime_pending_scope(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = MagicMock()
        runtime.context = {"thread_id": "test-thread"}
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        fallback_run_id = str(id(runtime))
        assert mw._pending_warnings.get(_pending_key(run_id=fallback_run_id))

        request = _make_request([AIMessage(content="hi")], runtime)
        captured, handler = _capture_handler()
        mw.wrap_model_call(request, handler)

        loop_warnings = [message for message in captured[0].messages if isinstance(message, HumanMessage) and message.name == "loop_warning"]
        assert len(loop_warnings) == 1
        assert "LOOP DETECTED" in loop_warnings[0].content
        assert not mw._pending_warnings.get(_pending_key(run_id=fallback_run_id))

    def test_before_agent_clears_stale_pending_warnings_for_thread(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime_a = _make_runtime(run_id="run-A")
        runtime_b = _make_runtime(run_id="run-B")
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime_a)

        assert mw._pending_warnings.get(_pending_key(run_id="run-A"))
        mw.before_agent({"messages": []}, runtime_b)
        assert not mw._pending_warnings.get(_pending_key(run_id="run-A"))

    def test_after_agent_clears_current_run_pending_warnings(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        assert mw._pending_warnings.get(_pending_key())
        mw.after_agent({"messages": []}, runtime)
        assert not mw._pending_warnings.get(_pending_key())

    def test_multiple_pending_warnings_are_merged_into_one_message(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        mw._pending_warnings[_pending_key()] = ["first warning", "second warning", "first warning"]
        request = _make_request([AIMessage(content="hi")], runtime)
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        loop_warnings = [message for message in captured[0].messages if isinstance(message, HumanMessage) and message.name == "loop_warning"]
        assert len(loop_warnings) == 1
        assert loop_warnings[0].content == "first warning\n\nsecond warning"

    def test_warn_only_queued_once_per_hash(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for _ in range(2):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=call), runtime)
        assert len(mw._pending_warnings[_pending_key()]) == 1

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=call), runtime)
        assert len(mw._pending_warnings[_pending_key()]) == 1

    def test_hard_stop_at_limit(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert isinstance(msgs[0], AIMessage)
        assert msgs[0].tool_calls == []
        assert _HARD_STOP_MSG in msgs[0].content

    def test_hard_stop_stamps_loop_capped_stop_reason(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        hard_stop_result = mw._apply(_make_state(tool_calls=call), runtime)
        assert hard_stop_result is not None

        assert mw.consume_stop_reason("test-run") == "loop_capped"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert mw.consume_stop_reason("test-run") is None

    def test_warn_only_does_not_stamp_stop_reason(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=call), runtime)
        mw._apply(_make_state(tool_calls=call), runtime)

        assert mw.consume_stop_reason("test-run") is None

    def test_tool_frequency_hard_stop_stamps_loop_capped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=2, tool_freq_hard_limit=3)
        runtime = _make_runtime()
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(3):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            if i < 2:
                assert result is None, f"unexpected hard stop at call {i}"

        assert mw.consume_stop_reason("test-run") == "loop_capped"

    def test_hard_stop_stamps_loop_capped_with_explicit_none_run_id(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = SimpleNamespace(context={"thread_id": "t", "run_id": None})
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)
        hard_stop = mw._apply(_make_state(tool_calls=call), runtime)
        assert hard_stop is not None

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert mw.consume_stop_reason(None) == "loop_capped"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert mw.consume_stop_reason(None) is None

    def test_different_calls_dont_trigger(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = _make_runtime()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(10):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            assert result is None

    def test_window_sliding(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=3, window_size=5)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=call), runtime)
        mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(5):
            mw._apply(_make_state(tool_calls=[_bash_call(f"other_{i}")]), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

    def test_reset_clears_state(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        mw._apply(_make_state(tool_calls=call), runtime)
        mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw.reset()
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None
        assert not mw._pending_warnings.get(_pending_key())

    def test_non_ai_message_ignored(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        state = {"messages": [SystemMessage(content="hello")]}
        result = mw._apply(state, runtime)
        assert result is None

    def test_empty_messages_ignored(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        result = mw._apply({"messages": []}, runtime)
        assert result is None

    def test_thread_id_from_runtime_context(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime_a = _make_runtime("thread-A")
        runtime_b = _make_runtime("thread-B")
        call = [_bash_call("ls")]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=call), runtime_a)
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=call), runtime_b)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=call), runtime_a)
        assert mw._pending_warnings.get(_pending_key("thread-A"))
        assert "LOOP DETECTED" in mw._pending_warnings[_pending_key("thread-A")][0]
        assert not mw._pending_warnings.get(_pending_key("thread-B"))

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=call), runtime_b)
        assert mw._pending_warnings.get(_pending_key("thread-B"))
        assert "LOOP DETECTED" in mw._pending_warnings[_pending_key("thread-B")][0]

    def test_lru_eviction(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, max_tracked_threads=3)
        call = [_bash_call("ls")]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(3):
            runtime = _make_runtime(f"thread-{i}")
            mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        runtime_new = _make_runtime("thread-new")
        mw._apply(_make_state(tool_calls=call), runtime_new)

        assert "thread-0" not in mw._history
        assert "thread-0" not in mw._tool_name_history
        assert "thread-new" in mw._history
        assert len(mw._history) == 3

    def test_warned_hashes_are_pruned_to_sliding_window(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=100, window_size=4)
        runtime = _make_runtime()

        for i in range(12):
            call = [_bash_call(f"cmd_{i}")]
            mw._apply(_make_state(tool_calls=call), runtime)
            mw._apply(_make_state(tool_calls=call), runtime)

        assert len(mw._history["test-thread"]) <= 4
        assert set(mw._warned["test-thread"]).issubset(set(mw._history["test-thread"]))
        assert len(mw._warned["test-thread"]) <= 4

    def test_pending_warning_keys_are_capped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, max_tracked_threads=2)

        for i in range(10):
            runtime = _make_runtime(thread_id="same-thread", run_id=f"run-{i}")
            mw._queue_pending_warning(runtime, f"warning-{i}")

        assert len(mw._pending_warnings) == mw._max_pending_warning_keys
        assert len(mw._pending_warning_touch_order) == mw._max_pending_warning_keys
        assert _pending_key("same-thread", "run-9") in mw._pending_warnings

    def test_pending_warning_list_is_capped_and_deduped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()

        for i in range(_MAX_PENDING_WARNINGS_PER_RUN + 4):
            mw._queue_pending_warning(runtime, f"warning-{i}")
        mw._queue_pending_warning(runtime, f"warning-{_MAX_PENDING_WARNINGS_PER_RUN + 3}")

        warnings = mw._pending_warnings[_pending_key()]
        assert len(warnings) == _MAX_PENDING_WARNINGS_PER_RUN
        assert warnings == [f"warning-{i}" for i in range(4, _MAX_PENDING_WARNINGS_PER_RUN + 4)]

    def test_pending_warning_touch_order_cleared_with_pending_key(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        mw._queue_pending_warning(runtime, "warning")

        mw.after_agent({"messages": []}, runtime)

        assert mw._pending_warnings == {}
        assert mw._pending_warning_touch_order == OrderedDict()

    def test_thread_safe_mutations(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware()
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert hasattr(mw, "_lock")
        assert isinstance(mw._lock, type(mw._lock))

    def test_fallback_thread_id_when_missing(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = MagicMock()
        runtime.context = {}
        call = [_bash_call("ls")]

        mw._apply(_make_state(tool_calls=call), runtime)
        assert "default" in mw._history


class TestLoopDetectionAgentGraphIntegration:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_loop_warning_is_transient_in_real_agent_graph(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

        @as_tool
        def bash(command: str) -> str:
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return f"ran: {command}"

        repeated_calls = [[{"name": "bash", "id": f"call_ls_{i}", "args": {"command": "ls"}}] for i in range(3)]
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        model = _CapturingFakeMessagesListChatModel(
            responses=[
                AIMessage(content="", tool_calls=repeated_calls[0]),
                AIMessage(content="", tool_calls=repeated_calls[1]),
                AIMessage(content="", tool_calls=repeated_calls[2]),
                AIMessage(content="final answer"),
            ],
        )
        graph = create_agent(model=model, tools=[bash], middleware=[mw])

        result = graph.invoke(
            {"messages": [("user", "inspect the directory")]},
            context={"thread_id": "integration-thread", "run_id": "integration-run"},
            config={"recursion_limit": 20},
        )

        assert len(model.seen_messages) == 4
        loop_warnings_by_call = [[message for message in messages if isinstance(message, HumanMessage) and message.name == "loop_warning"] for messages in model.seen_messages]
        assert loop_warnings_by_call[0] == []
        assert loop_warnings_by_call[1] == []
        assert loop_warnings_by_call[2] == []
        assert len(loop_warnings_by_call[3]) == 1
        assert "LOOP DETECTED" in loop_warnings_by_call[3][0].content

        fourth_request = model.seen_messages[3]
        assert isinstance(fourth_request[-2], ToolMessage)
        assert fourth_request[-2].tool_call_id == "call_ls_2"
        assert fourth_request[-1] is loop_warnings_by_call[3][0]

        persisted_loop_warnings = [message for message in result["messages"] if isinstance(message, HumanMessage) and message.name == "loop_warning"]
        assert persisted_loop_warnings == []
        assert result["messages"][-1].content == "final answer"
        assert mw._pending_warnings == {}
        assert mw._pending_warning_touch_order == OrderedDict()

    @pytest.mark.asyncio
    async def test_loop_warning_is_transient_in_async_agent_graph(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""

        @as_tool
        async def bash(command: str) -> str:
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return f"ran: {command}"

        repeated_calls = [[{"name": "bash", "id": f"call_async_ls_{i}", "args": {"command": "ls"}}] for i in range(3)]
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        model = _CapturingFakeMessagesListChatModel(
            responses=[
                AIMessage(content="", tool_calls=repeated_calls[0]),
                AIMessage(content="", tool_calls=repeated_calls[1]),
                AIMessage(content="", tool_calls=repeated_calls[2]),
                AIMessage(content="async final answer"),
            ],
        )
        graph = create_agent(model=model, tools=[bash], middleware=[mw])

        result = await graph.ainvoke(
            {"messages": [("user", "inspect the directory asynchronously")]},
            context={"thread_id": "async-integration-thread", "run_id": "async-integration-run"},
            config={"recursion_limit": 20},
        )

        assert len(model.seen_messages) == 4
        loop_warnings_by_call = [[message for message in messages if isinstance(message, HumanMessage) and message.name == "loop_warning"] for messages in model.seen_messages]
        assert loop_warnings_by_call[0] == []
        assert loop_warnings_by_call[1] == []
        assert loop_warnings_by_call[2] == []
        assert len(loop_warnings_by_call[3]) == 1
        assert "LOOP DETECTED" in loop_warnings_by_call[3][0].content

        fourth_request = model.seen_messages[3]
        assert isinstance(fourth_request[-2], ToolMessage)
        assert fourth_request[-2].tool_call_id == "call_async_ls_2"
        assert fourth_request[-1] is loop_warnings_by_call[3][0]

        persisted_loop_warnings = [message for message in result["messages"] if isinstance(message, HumanMessage) and message.name == "loop_warning"]
        assert persisted_loop_warnings == []
        assert result["messages"][-1].content == "async final answer"
        assert mw._pending_warnings == {}
        assert mw._pending_warning_touch_order == OrderedDict()


class TestAppendText:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def test_none_content_returns_text(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        result = LoopDetectionMiddleware._append_text(None, "hello")
        assert result == "hello"

    def test_str_content_concatenates(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        result = LoopDetectionMiddleware._append_text("existing", "appended")
        assert result == "existing\n\nappended"

    def test_empty_str_content_concatenates(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        result = LoopDetectionMiddleware._append_text("", "appended")
        assert result == "\n\nappended"

    def test_list_content_appends_text_block(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        content = [
            {"type": "thinking", "text": "Let me think..."},
            {"type": "text", "text": "Here is my answer"},
        ]
        result = LoopDetectionMiddleware._append_text(content, "stop msg")
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == content[0]
        assert result[1] == content[1]
        assert result[2] == {"type": "text", "text": "\n\nstop msg"}

    def test_empty_list_content_appends_text_block(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        result = LoopDetectionMiddleware._append_text([], "stop msg")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == {"type": "text", "text": "\n\nstop msg"}

    def test_unexpected_type_coerced_to_str(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        result = LoopDetectionMiddleware._append_text(42, "stop msg")
        assert isinstance(result, str)
        assert result == "42\n\nstop msg"

    def test_list_content_not_mutated_in_place(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        original = [{"type": "text", "text": "hello"}]
        result = LoopDetectionMiddleware._append_text(original, "appended")
        assert len(original) == 1  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert len(result) == 2  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestHardStopWithListContent:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def test_hard_stop_with_list_content(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        list_content = [
            {"type": "thinking", "text": "Let me think..."},
            {"type": "text", "text": "I'll run ls"},
        ]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call, content=list_content), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=call, content=list_content), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.tool_calls == []
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert isinstance(msg.content, list)
        assert len(msg.content) == 3
        assert msg.content[2]["type"] == "text"
        assert _HARD_STOP_MSG in msg.content[2]["text"]

    def test_hard_stop_with_none_content(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg.content, str)
        assert _HARD_STOP_MSG in msg.content

    def test_hard_stop_with_str_content(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call, content="thinking..."), runtime)

        result = mw._apply(_make_state(tool_calls=call, content="thinking..."), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg.content, str)
        assert msg.content.startswith("thinking...")
        assert _HARD_STOP_MSG in msg.content

    def test_hard_stop_clears_raw_tool_call_metadata(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        def _make_provider_state():
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return {
                "messages": [
                    AIMessage(
                        content="thinking...",
                        tool_calls=call,
                        additional_kwargs={
                            "tool_calls": [
                                {
                                    "id": "call_ls",
                                    "type": "function",
                                    "function": {"name": "bash", "arguments": '{"command":"ls"}'},
                                    "thought_signature": "sig-1",
                                }
                            ],
                            "function_call": {"name": "bash", "arguments": '{"command":"ls"}'},
                        },
                        response_metadata={"finish_reason": "tool_calls"},
                    )
                ]
            }

        for _ in range(3):
            mw._apply(_make_provider_state(), runtime)

        result = mw._apply(_make_provider_state(), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert msg.tool_calls == []
        assert "tool_calls" not in msg.additional_kwargs
        assert "function_call" not in msg.additional_kwargs
        assert msg.response_metadata["finish_reason"] == "stop"


class TestToolFrequencyDetection:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def _read_call(self, path):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return {"name": "read_file", "id": f"call_read_{path}", "args": {"path": path}}

    def test_below_freq_warn_returns_none(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=5, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        for i in range(4):
            result = mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)
            assert result is None

    def test_freq_warn_at_threshold(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=5, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        for i in range(4):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_4.py")]), runtime)
        assert result is None
        queued = mw._pending_warnings.get(_pending_key(), [])
        assert queued
        assert "read_file" in queued[0]
        assert "LOOP DETECTED" in queued[0]

    def test_freq_warn_only_queued_once(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw._apply(_make_state(tool_calls=[self._read_call("/file_2.py")]), runtime)
        assert len(mw._pending_warnings[_pending_key()]) == 1

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_3.py")]), runtime)
        assert result is None
        assert len(mw._pending_warnings[_pending_key()]) == 1

    def test_freq_hard_stop_at_limit(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=6)
        runtime = _make_runtime()

        for i in range(5):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_5.py")]), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.tool_calls == []
        assert "FORCED STOP" in msg.content
        assert "read_file" in msg.content

    def test_windowed_frequency_decay_avoids_hard_stop_when_interleaved(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=100, tool_freq_hard_limit=4, window_size=5)
        runtime = _make_runtime()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        read_count = 0
        for i in range(8):
            result = mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)
            assert result is None, f"read call {i} unexpectedly hard-stopped"
            read_count += 1
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            assert result is None, f"bash call {i} unexpectedly hard-stopped"

        assert read_count == 8  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    def test_rapid_identical_tool_type_in_one_window_still_hard_stops(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=100, tool_freq_hard_limit=4, window_size=5)
        runtime = _make_runtime()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(3):
            assert mw._apply(_make_state(tool_calls=[self._read_call(f"/f_{i}.py")]), runtime) is None

        result = mw._apply(_make_state(tool_calls=[self._read_call("/f_3.py")]), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.tool_calls == []
        assert "FORCED STOP" in msg.content
        assert "read_file" in msg.content

    def test_different_tools_tracked_independently(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(2):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            assert result is None

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_2.py")]), runtime)
        assert result is None
        assert "read_file" in mw._pending_warnings[_pending_key()][0]

    def test_freq_reset_clears_state(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        mw.reset()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_new.py")]), runtime)
        assert result is None

    def test_freq_reset_per_thread_clears_only_target(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime_a = _make_runtime("thread-A")
        runtime_b = _make_runtime("thread-B")

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/a_{i}.py")]), runtime_a)
            mw._apply(_make_state(tool_calls=[self._read_call(f"/b_{i}.py")]), runtime_b)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        mw.reset(thread_id="thread-A")

        assert "thread-A" not in mw._tool_name_history

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/b_2.py")]), runtime_b)
        assert result is None
        assert "LOOP DETECTED" in mw._pending_warnings[_pending_key("thread-B")][0]

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/a_new.py")]), runtime_a)
        assert result is None

    def test_freq_per_thread_isolation(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime_a = _make_runtime("thread-A")
        runtime_b = _make_runtime("thread-B")

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime_a)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/other_{i}.py")]), runtime_b)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_2.py")]), runtime_a)
        assert result is None
        assert "LOOP DETECTED" in mw._pending_warnings[_pending_key("thread-A")][0]
        assert not mw._pending_warnings.get(_pending_key("thread-B"))

    def test_multi_tool_single_response_counted(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(tool_freq_warn=5, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        call = [self._read_call("/a.py"), self._read_call("/b.py")]
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        call = [self._read_call("/c.py"), self._read_call("/d.py")]
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/e.py")]), runtime)
        assert result is None
        assert "read_file" in mw._pending_warnings[_pending_key()][0]

    def test_override_tool_uses_override_thresholds(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(
            tool_freq_warn=5,
            tool_freq_hard_limit=10,
            tool_freq_overrides={"bash": (50, 100)},
        )
        runtime = _make_runtime()

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(10):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            assert result is None, f"unexpected trigger on call {i + 1}"

    def test_non_override_tool_falls_back_to_global(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(
            tool_freq_warn=3,
            tool_freq_hard_limit=6,
            tool_freq_overrides={"bash": (50, 100)},
        )
        runtime = _make_runtime()

        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_2.py")]), runtime)
        assert result is None
        queued = mw._pending_warnings.get(_pending_key(), [])
        assert queued
        assert "read_file" in queued[0]

    def test_hash_detection_takes_priority(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware(
            warn_threshold=2,
            hard_limit=3,
            tool_freq_warn=100,
            tool_freq_hard_limit=200,
        )
        runtime = _make_runtime()
        call = [self._read_call("/same_file.py")]

        for _ in range(2):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert _HARD_STOP_MSG in msg.content


class TestFromConfig:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    @staticmethod
    def _config(**kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        from deerflow.config.loop_detection_config import LoopDetectionConfig

        return LoopDetectionConfig(**kwargs)

    def test_scalar_fields_mapped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        config = self._config(
            warn_threshold=4,
            hard_limit=8,
            window_size=15,
            max_tracked_threads=50,
            tool_freq_warn=20,
            tool_freq_hard_limit=40,
        )
        mw = LoopDetectionMiddleware.from_config(config)
        assert mw.warn_threshold == 4
        assert mw.hard_limit == 8
        assert mw.window_size == 15
        assert mw.max_tracked_threads == 50
        assert mw.tool_freq_warn == 20
        assert mw.tool_freq_hard_limit == 40

    def test_overrides_converted_to_tuples(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        config = self._config(tool_freq_overrides={"bash": {"warn": 50, "hard_limit": 100}})
        mw = LoopDetectionMiddleware.from_config(config)
        assert mw._tool_freq_overrides == {"bash": (50, 100)}

    def test_empty_overrides(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware.from_config(self._config())
        assert mw._tool_freq_overrides == {}

    def test_constructed_middleware_queues_loop_warning(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware.from_config(self._config(warn_threshold=2, hard_limit=4))
        runtime = _make_runtime()
        call = [_bash_call("ls")]
        mw._apply(_make_state(tool_calls=call), runtime)
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None
        queued = mw._pending_warnings.get(_pending_key(), [])
        assert queued
        assert "LOOP DETECTED" in queued[0]

    def test_freq_window_sized_to_hard_limit_under_defaults(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware.from_config(self._config())
        assert mw._tool_freq_window >= mw.tool_freq_hard_limit
        assert mw._tool_freq_window >= mw.tool_freq_warn

    def test_freq_window_covers_largest_override_hard_limit(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware.from_config(self._config(tool_freq_overrides={"bash": {"warn": 60, "hard_limit": 120}}))
        assert mw._tool_freq_window >= 120

    def test_tight_burst_hard_stops_under_default_config(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        mw = LoopDetectionMiddleware.from_config(self._config())
        runtime = _make_runtime()
        hard = mw.tool_freq_hard_limit  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        for i in range(hard - 1):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            assert result is None, f"unexpected hard stop before the limit at call {i}"

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{hard}")]), runtime)
        assert result is not None
        assert mw.consume_stop_reason("test-run") == "loop_capped"
