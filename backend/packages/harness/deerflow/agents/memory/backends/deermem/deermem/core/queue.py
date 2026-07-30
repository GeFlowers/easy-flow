'定义 queue 模块提供的职责与可复用接口。\n\nMemory update queue with debounce mechanism.'

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
    '封装 ConversationContext 的状态、协作关系与公开操作。\n\nContext for a conversation to be processed for memory update.'

    thread_id: str
    messages: list[Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    agent_name: str | None = None
    user_id: str | None = None
    trace_id: str | None = None
    correction_detected: bool = False
    reinforcement_detected: bool = False


class MemoryUpdateQueue:
    '封装 MemoryUpdateQueue 的状态、协作关系与公开操作。\n\nQueue for memory updates with debounce mechanism.\n\n    This queue collects conversation contexts and processes them after\n    a configurable debounce period. Multiple conversations received within\n    the debounce window are batched together.\n    '

    def __init__(self, config: DeerMemConfig, updater: MemoryUpdater):
        '实现 __init__ 协议方法，保持对象交互语义一致。\n\nInitialize the memory update queue with injected config + updater.'
        self._config = config
        self._updater = updater
        self._queue: list[ConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False
        # Thread currently running ``_process_queue`` (None when idle). ``flush_sync``
        # joins an in-flight worker instead of reporting a false-positive "completed"
        # while contexts it already pulled out of the queue are still being processed
        # (and would be lost on exit). See ``flush_sync`` step (1).
        self._processing_thread: threading.Thread | None = None
        self._reprocess_pending = False

    @staticmethod
    def _queue_key(
        thread_id: str,
        user_id: str | None,
        agent_name: str | None,
    ) -> tuple[str, str | None, str | None]:
        '执行 _queue_key 的明确职责，并返回与调用约定一致的结果。\n\nReturn the debounce identity for a memory update target.'
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
        '执行 add 的明确职责，并返回与调用约定一致的结果。\n\nAdd a conversation to the update queue.\n\n        Args:\n            thread_id: The thread ID.\n            messages: The conversation messages.\n            agent_name: If provided, memory is stored per-agent. If None, uses global memory.\n            user_id: The user ID captured at enqueue time. Stored in ConversationContext so it\n                survives the threading.Timer boundary (ContextVar does not propagate across\n                raw threads).\n            trace_id: Request trace id captured at enqueue time so the\n                later Timer thread can attach it to memory LLM tracing metadata.\n            correction_detected: Whether recent turns include an explicit correction signal.\n            reinforcement_detected: Whether recent turns include a positive reinforcement signal.\n        '
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
        '执行 add_nowait 的明确职责，并返回与调用约定一致的结果。\n\nAdd a conversation and start processing immediately in the background.'
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
        '执行 _enqueue_locked 的明确职责，并返回与调用约定一致的结果'
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
        '执行 _reset_timer 的明确职责，并返回与调用约定一致的结果。\n\nReset the debounce timer.'
        config = self._config
        self._schedule_timer(config.debounce_seconds)

        logger.debug("Memory update timer set for %ss", config.debounce_seconds)

    def _schedule_timer(self, delay_seconds: float) -> None:
        '执行 _schedule_timer 的明确职责，并返回与调用约定一致的结果。\n\nSchedule queue processing after the provided delay.'
        # Cancel existing timer if any
        if self._timer is not None:
            self._timer.cancel()

        self._timer = threading.Timer(
            delay_seconds,
            self._process_queue,
        )
        self._timer.daemon = True
        self._timer.start()

    def _process_queue(self, *, skip_inter_item_delay: bool = False) -> None:
        '执行 _process_queue 的明确职责，并返回与调用约定一致的结果。\n\nProcess all queued conversation contexts.\n\n        Args:\n            skip_inter_item_delay: When set, skip the inter-item rate-limit\n                ``time.sleep``. Intended for the shutdown-drain path\n                (:meth:`flush_sync`), which races a bounded timeout and should\n                not waste budget sleeping between items.\n        '
        with self._lock:
            if self._processing:
                # Another worker is already draining the queue. Instead of
                # spawning a tight timer spin (repeatedly re-scheduling a
                # 0-delay Timer thread while busy), defer a single re-run: the
                # active worker checks this flag in its finally block and
                # reschedules once if work remains.
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

                # Small delay between updates to avoid rate limiting.
                # Skipped on the shutdown-drain path, which races a bounded
                # timeout and should spend that budget on LLM calls, not on
                # sleeping between items.
                if not skip_inter_item_delay and len(contexts_to_process) > 1:
                    time.sleep(0.5)
        finally:
            # Summary count disambiguates "drained" (queue emptied) from "saved"
            # (every extraction persisted): per-item ``update_memory`` failures are
            # swallowed above, so without this an operator debugging missing
            # memories would see only the happy-path "Processing N" line.
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
        '执行 flush 的明确职责，并返回与调用约定一致的结果。\n\nForce immediate processing of the queue.\n\n        This is useful for testing or graceful shutdown.\n\n        Args:\n            skip_inter_item_delay: Forwarded to :meth:`_process_queue`; skip the\n                inter-item rate-limit sleep. Intended for the shutdown-drain\n                path (:meth:`flush_sync`).\n        '
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        self._process_queue(skip_inter_item_delay=skip_inter_item_delay)

    def flush_sync(self, timeout: float) -> bool:
        '执行 flush_sync 的明确职责，并返回与调用约定一致的结果。\n\nBest-effort synchronous flush bounded by ``timeout`` seconds.\n\n        Unlike :meth:`flush_nowait` (which only schedules a daemon timer that\n        is killed on process exit), this runs :meth:`flush` on a daemon thread\n        and waits up to ``timeout`` seconds for it to finish. Intended for\n        graceful shutdown: without it, any updates enqueued since the last\n        timer fire are lost on restart / rolling deploy / SIGTERM, because the\n        queue is pure in-memory and the debounce Timer is a daemon thread.\n\n        The drain accounts for two races a naive ``flush()`` would miss:\n\n        - **In-flight worker.** If the debounce Timer already fired, an\n          ``_process_queue`` worker is mid-LLM-call holding contexts it already\n          pulled out of the queue (``_processing=True``, queue empty). ``flush``\n          alone would see ``_processing=True``, no-op, and report success while\n          that worker is still running and likely killed on exit. So we join\n          the in-flight worker first (bounded by the remaining budget).\n        - **Failed flush.** ``flush`` makes a synchronous LLM call that can\n          raise; success is tracked on the happy path only, so the return value\n          matches the docstring\'s "completed".\n\n        Note: steps (1) and (3) share the same ``deadline`` budget. A slow\n        in-flight worker can consume most/all of it, leaving step (3) to no-op;\n        ``timeout`` must therefore cover both a slow in-flight worker *and* the\n        remaining queue (best-effort: any tail not drained in budget is dropped,\n        same failure direction as no flush, scoped to the tail).\n\n        Returns ``True`` only if the drain genuinely finished (queue empty, no\n        worker still running, flush did not raise) within ``timeout``.\n        '
        deadline = time.monotonic() + timeout

        # (1) Wait for an in-flight _process_queue first (bounded). Otherwise
        # flush() would see _processing=True, no-op, and we would report
        # success while that worker is still mid-LLM-call on a daemon thread
        # that exit will kill — losing the contexts it already pulled out.
        with self._lock:
            in_flight = self._processing_thread
        if in_flight is not None:
            in_flight.join(timeout=max(0.0, deadline - time.monotonic()))

        # (2) Genuine idle: nothing pending and no worker still running.
        if self.pending_count == 0 and not self.is_processing:
            return True

        # (3) Drain the queue on a daemon thread so the timeout is a real hard
        # stop: flush() makes a synchronous LLM call that cannot be
        # interrupted, so we wait on Event.wait, not on Thread.join.
        success = False
        done = threading.Event()

        def _run() -> None:
            '执行 _run 的明确职责，并返回与调用约定一致的结果'
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
        # flush() returned; only report success if no worker raced back in.
        return bool(success) and not self.is_processing

    def flush_nowait(self) -> None:
        '执行 flush_nowait 的明确职责，并返回与调用约定一致的结果。\n\nStart queue processing immediately in a background thread.'
        with self._lock:
            # Daemon thread: queued messages may be lost if the process exits
            # before _process_queue completes. Acceptable for best-effort memory updates.
            self._schedule_timer(0)

    def clear(self) -> None:
        '执行 clear 的明确职责，并返回与调用约定一致的结果。\n\nClear the queue without processing.\n\n        This is useful for testing.\n        '
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
        '执行 pending_count 的明确职责，并返回与调用约定一致的结果。\n\nGet the number of pending updates.'
        with self._lock:
            return len(self._queue)

    @property
    def is_processing(self) -> bool:
        '判断条件是否成立并返回布尔结果，并遵守 is_processing 所表达的接口约束。\n\nCheck if the queue is currently being processed.'
        with self._lock:
            return self._processing
