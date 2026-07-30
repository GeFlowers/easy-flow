"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""
import threading
import time
from unittest.mock import MagicMock, call, patch

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import ConversationContext, MemoryUpdateQueue


def _queue(updater: MagicMock | None = None) -> MemoryUpdateQueue:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return MemoryUpdateQueue(DeerMemConfig(), updater or MagicMock())


def test_queue_add_preserves_existing_correction_flag_for_same_thread() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["first"], correction_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], correction_detected=False)

    assert len(queue._queue) == 1
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].correction_detected is True


def test_process_queue_forwards_correction_flag_to_updater() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent", correction_detected=True)]

    queue._process_queue()

    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=True,
        reinforcement_detected=False,
        user_id=None,
        trace_id=None,
    )


def test_queue_add_preserves_existing_reinforcement_flag_for_same_thread() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["first"], reinforcement_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], reinforcement_detected=False)

    assert len(queue._queue) == 1
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].reinforcement_detected is True


def test_process_queue_forwards_reinforcement_flag_to_updater() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent", reinforcement_detected=True)]

    queue._process_queue()

    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=False,
        reinforcement_detected=True,
        user_id=None,
        trace_id=None,
    )


def test_flush_nowait_cancels_existing_timer_and_starts_immediate_timer() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    existing_timer = MagicMock()
    queue._timer = existing_timer
    created_timer = MagicMock()

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue.flush_nowait()

    existing_timer.cancel.assert_called_once_with()
    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()
    assert queue._timer is created_timer


def test_add_nowait_cancels_existing_timer_and_starts_immediate_timer() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    existing_timer = MagicMock()
    queue._timer = existing_timer
    created_timer = MagicMock()

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue.add_nowait(thread_id="thread-1", messages=["conversation"], agent_name="lead-agent")

    existing_timer.cancel.assert_called_once_with()
    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert queue.pending_count == 1
    assert queue._queue[0].agent_name == "lead-agent"
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()


def test_process_queue_defers_reprocess_when_already_processing() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    queue._processing = True

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer") as timer_cls:
        queue._process_queue()

    timer_cls.assert_not_called()
    assert queue._reprocess_pending is True


def test_finishing_worker_reschedules_once_when_reprocess_pending() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_updater = MagicMock()
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["first"], agent_name="lead_agent")]
    queue._reprocess_pending = True
    created_timer = MagicMock()

    def _enqueue_more_while_processing(**_kwargs) -> bool:
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        queue._queue.append(ConversationContext(thread_id="thread-2", messages=["second"], agent_name="lead_agent"))
        return True

    mock_updater.update_memory.side_effect = _enqueue_more_while_processing

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue._process_queue()

    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()
    assert queue._reprocess_pending is False


def test_finishing_worker_does_not_reschedule_when_no_work_remains() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["only"], agent_name="lead_agent")]
    queue._reprocess_pending = True

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer") as timer_cls:
        queue._process_queue()

    timer_cls.assert_not_called()
    assert queue._reprocess_pending is False


def test_flush_nowait_is_non_blocking() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    started = threading.Event()
    finished = threading.Event()

    def _slow_process_queue() -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        started.set()
        time.sleep(0.2)
        finished.set()

    queue._process_queue = _slow_process_queue

    start = time.perf_counter()
    queue.flush_nowait()
    elapsed = time.perf_counter() - start

    assert started.wait(0.1) is True
    assert elapsed < 0.1
    assert finished.is_set() is False
    assert finished.wait(1.0) is True


def test_queue_keeps_updates_for_different_agents_in_same_thread() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["agent-a"], agent_name="agent-a")
        queue.add(thread_id="thread-1", messages=["agent-b"], agent_name="agent-b")

    assert queue.pending_count == 2
    assert [context.agent_name for context in queue._queue] == ["agent-a", "agent-b"]


def test_queue_still_coalesces_updates_for_same_agent_in_same_thread() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["first"], agent_name="agent-a", correction_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], agent_name="agent-a", correction_detected=False)

    assert queue.pending_count == 1
    assert queue._queue[0].agent_name == "agent-a"
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].correction_detected is True


def test_process_queue_updates_different_agents_in_same_thread_separately() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["agent-a"], agent_name="agent-a")
        queue.add(thread_id="thread-1", messages=["agent-b"], agent_name="agent-b")

    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue._updater = mock_updater

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.time.sleep"):
        queue.flush()

    assert mock_updater.update_memory.call_count == 2
    mock_updater.update_memory.assert_has_calls(
        [
            call(messages=["agent-a"], thread_id="thread-1", agent_name="agent-a", correction_detected=False, reinforcement_detected=False, user_id=None, trace_id=None),
            call(messages=["agent-b"], thread_id="thread-1", agent_name="agent-b", correction_detected=False, reinforcement_detected=False, user_id=None, trace_id=None),
        ]
    )


def test_process_queue_forwards_trace_id_to_updater() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent", trace_id="trace-memory-1")]

    queue._process_queue()

    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=False,
        reinforcement_detected=False,
        user_id=None,
        trace_id="trace-memory-1",
    )


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------

_QUEUE_MODULE = "deerflow.agents.memory.backends.deermem.deermem.core.queue"


def test_flush_sync_noop_on_empty_queue() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    assert queue.pending_count == 0
    assert queue.flush_sync(timeout=5.0) is True


def test_flush_sync_drains_pending_queue_and_returns_true() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent")]

    with (
        patch(_QUEUE_MODULE + ".MemoryUpdater", create=True),
        patch(_QUEUE_MODULE + ".time.sleep"),
    ):
        completed = queue.flush_sync(timeout=5.0)

    assert completed is True
    assert queue.pending_count == 0
    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=False,
        reinforcement_detected=False,
        user_id=None,
        trace_id=None,
    )


def test_flush_sync_returns_false_when_flush_exceeds_timeout() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent")]
    release = threading.Event()

    def _slow_flush() -> None:
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        release.wait(timeout=5.0)

    with patch.object(queue, "flush", side_effect=_slow_flush):
        completed = queue.flush_sync(timeout=0.1)

    assert completed is False
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert queue.pending_count == 1
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    release.set()


def _run_inflight_worker(queue: MemoryUpdateQueue, release: threading.Event) -> threading.Thread:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""

    def _inflight() -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        with queue._lock:
            queue._processing = True
            queue._processing_thread = threading.current_thread()
        release.wait(timeout=5.0)
        with queue._lock:
            queue._processing = False
            queue._processing_thread = None

    thread = threading.Thread(target=_inflight, name="fake-inflight-worker", daemon=True)
    thread.start()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    while not queue.is_processing:
        time.sleep(0.005)
    return thread


def test_flush_sync_waits_for_inflight_worker_and_returns_false_if_unfinished() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    release = threading.Event()
    inflight = _run_inflight_worker(queue, release)

    try:
        completed = queue.flush_sync(timeout=0.2)
    finally:
        release.set()
        inflight.join(timeout=5.0)

    assert completed is False


def test_flush_sync_returns_true_when_inflight_worker_finishes_in_budget() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    release = threading.Event()
    inflight = _run_inflight_worker(queue, release)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    release.set()

    completed = queue.flush_sync(timeout=5.0)
    inflight.join(timeout=5.0)

    assert completed is True
    assert queue.is_processing is False
    assert queue._processing_thread is None


def test_flush_sync_returns_false_when_flush_raises() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    queue = _queue()
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent")]

    with patch.object(queue, "flush", side_effect=RuntimeError("boom")):
        completed = queue.flush_sync(timeout=5.0)

    assert completed is False


def test_flush_sync_skips_inter_item_delay_on_drain_path() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id=f"thread-{i}", messages=["conversation"], agent_name="lead_agent") for i in range(3)]

    with patch(_QUEUE_MODULE + ".time.sleep") as mock_sleep:
        completed = queue.flush_sync(timeout=5.0)

    assert completed is True
    assert queue.pending_count == 0
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    mock_sleep.assert_not_called()
    assert mock_updater.update_memory.call_count == 3
