"""为社区沙箱 Provider 提供预热实例的容量控制与空闲回收逻辑。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_IDLE_TIMEOUT = 600
DEFAULT_REPLICAS = 3
IDLE_CHECK_INTERVAL = 60


class WarmPoolLifecycleMixin[WarmEntryT]:
    """管理预热沙箱的副本上限、过期清理和后台巡检线程。

    具体 Provider 负责定义活动实例计数与实例销毁方式；本混入类只
    维护预热池生命周期，所有池状态读写均通过 ``_lock`` 保护。
    """

    DEFAULT_IDLE_TIMEOUT = DEFAULT_IDLE_TIMEOUT
    DEFAULT_REPLICAS = DEFAULT_REPLICAS
    IDLE_CHECK_INTERVAL = IDLE_CHECK_INTERVAL
    _idle_checker_thread_name = "warm-pool-idle-checker"

    _lock: threading.Lock
    _warm_pool: dict[str, tuple[WarmEntryT, float]]
    _config: dict[str, Any]
    _idle_checker_stop: threading.Event
    _idle_checker_thread: threading.Thread | None

    def _active_count_locked(self) -> int:
        """在调用方持有 ``_lock`` 时返回正在使用的沙箱数量。"""
        raise NotImplementedError

    def _destroy_warm_entry(self, sandbox_id: str, entry: WarmEntryT, *, reason: str) -> None:
        """销毁已从预热池移除的实例；由具体 Provider 执行资源回收。"""
        raise NotImplementedError

    def _replica_count(self) -> tuple[int, int]:
        """返回配置的副本上限，以及活动实例与预热实例的总数。"""
        replicas = int(self._config.get("replicas", DEFAULT_REPLICAS))
        with self._lock:
            total = self._active_count_locked() + len(self._warm_pool)
        return replicas, total

    def _log_replicas_soft_cap(self, replicas: int, sandbox_id: str, evicted: str | None) -> None:
        """记录副本软上限的处理结果：已淘汰实例或因活动实例占满而超限。"""
        if evicted is not None:
            logger.info("Evicted warm-pool sandbox %s to stay within replicas=%s", evicted, replicas)
            return

        logger.warning(
            "All %s replica slots are in active use; creating sandbox %s beyond the soft limit",
            replicas,
            sandbox_id,
        )

    def _evict_oldest_warm(self) -> str | None:
        """移除并销毁池中最早加入的预热实例，返回其 ID；池为空则返回 ``None``。"""
        with self._lock:
            if not self._warm_pool:
                return None
            sandbox_id, (entry, _) = min(self._warm_pool.items(), key=lambda item: item[1][1])
            self._warm_pool.pop(sandbox_id)

        self._destroy_warm_entry(sandbox_id, entry, reason="replica_enforcement")
        return sandbox_id

    def _reap_expired_warm(self, idle_timeout: float | None = None) -> None:
        """按空闲时长找出过期实例，先从池中摘除，再逐个释放底层资源。"""
        timeout = float(self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT) if idle_timeout is None else idle_timeout)
        if timeout <= 0:
            return

        now = time.time()
        expired: list[tuple[str, WarmEntryT]] = []
        with self._lock:
            for sandbox_id, (entry, timestamp) in self._warm_pool.items():
                if now - timestamp > timeout:
                    expired.append((sandbox_id, entry))
            for sandbox_id, _ in expired:
                self._warm_pool.pop(sandbox_id, None)

        for sandbox_id, entry in expired:
            self._destroy_warm_entry(sandbox_id, entry, reason="idle_timeout")

    def _start_idle_checker(self) -> None:
        """启动定期回收空闲实例的守护线程；已有巡检线程运行时不重复启动。"""
        if self._idle_checker_thread is not None and self._idle_checker_thread.is_alive():
            return

        self._idle_checker_stop.clear()
        self._idle_checker_thread = threading.Thread(
            target=self._idle_checker_loop,
            name=self._idle_checker_thread_name,
            daemon=True,
        )
        self._idle_checker_thread.start()
        logger.info("Started warm-pool idle checker thread (timeout: %ss)", self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT))

    def _stop_idle_checker(self) -> None:
        """通知巡检线程退出，并在非当前线程调用时等待其结束。"""
        self._idle_checker_stop.set()
        thread = self._idle_checker_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _idle_checker_loop(self) -> None:
        """按固定间隔触发空闲清理，直到收到停止信号；单轮异常只记录日志。"""
        idle_timeout = float(self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT))
        while not self._idle_checker_stop.wait(self.IDLE_CHECK_INTERVAL):
            try:
                self._cleanup_idle_resources(idle_timeout)
            except Exception:
                logger.exception("Error in warm-pool idle checker loop")

    def _cleanup_idle_resources(self, idle_timeout: float) -> None:
        """执行一轮空闲资源清理，将超时阈值交给预热池回收逻辑。"""
        self._reap_expired_warm(idle_timeout)


__all__ = [
    "DEFAULT_IDLE_TIMEOUT",
    "DEFAULT_REPLICAS",
    "IDLE_CHECK_INTERVAL",
    "WarmPoolLifecycleMixin",
]
