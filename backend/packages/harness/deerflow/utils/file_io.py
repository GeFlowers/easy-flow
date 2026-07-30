"""为文件系统工作提供专用的异步线程池卸载辅助函数。"""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def _default_file_io_workers() -> int:
    """读取环境变量并返回文件输入输出线程池的有效工作线程数。"""
    raw = os.getenv("DEER_FLOW_FILE_IO_WORKERS")
    if raw:
        try:
            workers = int(raw)
            if workers > 0:
                return workers
        except ValueError:
            pass
        logger.warning("Invalid DEER_FLOW_FILE_IO_WORKERS value; using default file IO worker count")
    return min(32, (os.cpu_count() or 1) + 4)


_FILE_IO_EXECUTOR = ThreadPoolExecutor(max_workers=_default_file_io_workers(), thread_name_prefix="file-io")


def _shutdown_file_io_executor() -> None:
    """在解释器退出时非阻塞地关闭文件输入输出线程池。"""
    _FILE_IO_EXECUTOR.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_file_io_executor)


async def run_file_io[**P, T](func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """在线程池中运行阻塞型文件操作，并保留当前的上下文变量。

    高层异步辅助函数会自动复制上下文变量，而底层执行器不会。
    因此此处显式复制当前上下文，确保用户作用域信息在线程中仍能正常工作。
    """
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_FILE_IO_EXECUTOR, ctx.run, call)
