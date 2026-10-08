'''按用户、代理和线程聚合待处理对话，并通过防抖定时器执行记忆更新。'''

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..config import DeerMemConfig

if TYPE_CHECKING:
    from .updater import MemoryUpdater

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    '''保存一组待处理对话及其目标身份、追踪信息和用户反馈信号。'''

    thread_id: str
    messages: list[Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    agent_name: str | None = None
    user_id: str | None = None
    trace_id: str | None = None
    correction_detected: bool = False
    reinforcement_detected: bool = False


class MemoryUpdateQueue:
    '''合并同一记忆目标的更新请求，并在线程中延迟批量处理，支持关闭时限内刷新。'''

    def __init__(self, config: DeerMemConfig, updater: MemoryUpdater):
        '''保存更新器与防抖配置，并初始化待处理项、线程锁和工作状态。'''
        self._config = config
        self._updater = updater
        self._queue: list[ConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False
        self._processing_thread: threading.Thread | None = None
        self._reprocess_pending = False

    @staticmethod
    def _queue_key(
        thread_id: str,
        user_id: str | None,
        agent_name: str | None,
    ) -> tuple[str, str | None, str | None]:
        '''组合线程、用户和代理标识，确定可以合并的记忆更新目标。'''
        return (thread_id, user_id, agent_name)

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
    ) -> None:
        '''登记或替换同一目标的待处理对话，并在最后一次请求后重新计时防抖窗口。'''
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                trace_id=trace_id,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
            )
            self._reset_timer()

        logger.info("Memory update queued for thread %s, queue size: %d", thread_id, len(self._queue))

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
    ) -> None:
        '''登记待处理对话并安排立即在后台刷新队列。'''
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                trace_id=trace_id,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
            )
            self._schedule_timer(0)

        logger.info("Memory update queued for immediate processing on thread %s, queue size: %d", thread_id, len(self._queue))

    def _enqueue_locked(
        self,
        *,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None,
        user_id: str | None,
        trace_id: str | None,
        correction_detected: bool,
        reinforcement_detected: bool,
    ) -> None:
        '''在锁保护下合并同一目标的对话上下文，并保留已检测到的反馈信号。'''
        queue_key = self._queue_key(thread_id, user_id, agent_name)
        existing_context = next(
            (context for context in self._queue if self._queue_key(context.thread_id, context.user_id, context.agent_name) == queue_key),
            None,
        )
        merged_correction_detected = correction_detected or (existing_context.correction_detected if existing_context is not None else False)
        merged_reinforcement_detected = reinforcement_detected or (existing_context.reinforcement_detected if existing_context is not None else False)
        context = ConversationContext(
            thread_id=thread_id,
            messages=messages,
            agent_name=agent_name,
            user_id=user_id,
            trace_id=trace_id,
            correction_detected=merged_correction_detected,
            reinforcement_detected=merged_reinforcement_detected,
        )

        self._queue = [context for context in self._queue if self._queue_key(context.thread_id, context.user_id, context.agent_name) != queue_key]
        self._queue.append(context)

    def _reset_timer(self) -> None:
        '''按配置的防抖时长重新安排队列处理。'''
        config = self._config
        self._schedule_timer(config.debounce_seconds)

        logger.debug("Memory update timer set for %ss", config.debounce_seconds)

    def _schedule_timer(self, delay_seconds: float) -> None:
        '''取消旧定时器并启动一个守护线程定时器，在指定延迟后处理队列。'''
        if self._timer is not None:
            self._timer.cancel()

        self._timer = threading.Timer(
            delay_seconds,
            self._process_queue,
        )
        self._timer.daemon = True
        self._timer.start()

    def _process_queue(self, *, skip_inter_item_delay: bool = False) -> None:
        '''原子取出当前队列并逐项更新记忆；并发触发时登记一次补跑，避免重复工作线程。'''
        with self._lock:
            if self._processing:
                self._reprocess_pending = True
                return

            if not self._queue:
                return

            self._processing = True
            self._processing_thread = threading.current_thread()
            contexts_to_process = self._queue.copy()
            self._queue.clear()
            self._timer = None

        logger.info("Processing %d queued memory updates", len(contexts_to_process))

        succeeded = 0
        failed = 0
        try:
            for context in contexts_to_process:
                try:
                    logger.info("Updating memory for thread %s (trace_id=%s)", context.thread_id, context.trace_id)
                    success = self._updater.update_memory(
                        messages=context.messages,
                        thread_id=context.thread_id,
                        agent_name=context.agent_name,
                        correction_detected=context.correction_detected,
                        reinforcement_detected=context.reinforcement_detected,
                        user_id=context.user_id,
                        trace_id=context.trace_id,
                    )
                    if success:
                        succeeded += 1
                        logger.info("Memory updated successfully for thread %s (trace_id=%s)", context.thread_id, context.trace_id)
                    else:
                        failed += 1
                        logger.warning("Memory update skipped/failed for thread %s (trace_id=%s)", context.thread_id, context.trace_id)
                except Exception as e:
                    failed += 1
                    logger.error("Error updating memory for thread %s (trace_id=%s): %s", context.thread_id, context.trace_id, e)

                if not skip_inter_item_delay and len(contexts_to_process) > 1:
                    time.sleep(0.5)
        finally:
            if succeeded or failed:
                logger.info("Memory update batch done: %d succeeded, %d failed", succeeded, failed)
            with self._lock:
                self._processing = False
                self._processing_thread = None
                if self._reprocess_pending:
                    self._reprocess_pending = False
                    if self._queue:
                        self._schedule_timer(0)

    def flush(self, *, skip_inter_item_delay: bool = False) -> None:
        '''取消尚未触发的防抖定时器，并在当前线程立即处理队列。'''
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        self._process_queue(skip_inter_item_delay=skip_inter_item_delay)

    def flush_sync(self, timeout: float) -> bool:
        '''在统一超时预算内等待正在处理的线程并尝试排空余项；仅完整结束时返回 True。'''
        deadline = time.monotonic() + timeout

        with self._lock:
            in_flight = self._processing_thread
        if in_flight is not None:
            in_flight.join(timeout=max(0.0, deadline - time.monotonic()))

        if self.pending_count == 0 and not self.is_processing:
            return True

        success = False
        done = threading.Event()

        def _run() -> None:
            '''在线程中刷新队列并记录异常，最后通知等待方刷新已结束。'''
            nonlocal success
            try:
                self.flush(skip_inter_item_delay=True)
                success = True
            except Exception:
                logger.exception("Memory queue flush failed during shutdown drain")
            finally:
                done.set()

        worker = threading.Thread(target=_run, name="memory-shutdown-flush", daemon=True)
        worker.start()
        finished = done.wait(timeout=max(0.0, deadline - time.monotonic()))
        if not finished:
            return False
        return bool(success) and not self.is_processing

    def flush_nowait(self) -> None:
        '''安排后台立即刷新，不等待更新完成。'''
        with self._lock:
            self._schedule_timer(0)

    def clear(self) -> None:
        '''取消定时器并清除排队项及处理状态，不执行记忆更新。'''
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._queue.clear()
            self._processing = False
            self._processing_thread = None
            self._reprocess_pending = False

    @property
    def pending_count(self) -> int:
        '''在线程锁保护下返回尚未被工作线程取走的更新项数量。'''
        with self._lock:
            return len(self._queue)

    @property
    def is_processing(self) -> bool:
        '''在线程锁保护下报告当前是否有工作线程正在处理更新。'''
        with self._lock:
            return self._processing
