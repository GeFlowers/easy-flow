'未说明'

import sys
import threading

from deerflow.mcp.session_pool import (
    MCPSessionPool,
    get_session_pool,
    reset_session_pool,
)


def test_get_session_pool_returns_one_singleton_under_concurrent_cold_start():
    '未说明'
    reset_session_pool()
    n_threads = 8
    pools: list[MCPSessionPool] = []
    pools_lock = threading.Lock()
    # Barrier makes all threads enter get_session_pool() together, so the
    # cold-start race is triggered rather than left to chance.
    barrier = threading.Barrier(n_threads)

    def get_pool() -> None:
        """处理获取 连接池相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        barrier.wait()
        pool = get_session_pool()
        with pools_lock:
            pools.append(pool)

    threads = [threading.Thread(target=get_pool) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len(pools) == n_threads
        assert len({id(pool) for pool in pools}) == 1
    finally:
        reset_session_pool()


def test_reset_racing_get_never_returns_none():
    '未说明'
    reset_session_pool()
    none_seen: list[int] = []
    none_seen_lock = threading.Lock()
    stop = threading.Event()

    def getter() -> None:
        '未说明'
        while not stop.is_set():
            if get_session_pool() is None:
                with none_seen_lock:
                    none_seen.append(1)

    def resetter() -> None:
        '未说明'
        for _ in range(100000):
            reset_session_pool()
        stop.set()

    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        getters = [threading.Thread(target=getter) for _ in range(4)]
        reset_thread = threading.Thread(target=resetter)
        for thread in getters:
            thread.start()
        reset_thread.start()
        for thread in getters:
            thread.join()
        reset_thread.join()
    finally:
        sys.setswitchinterval(previous_interval)
        reset_session_pool()

    assert not none_seen, "get_session_pool() returned None while a reset raced it"
