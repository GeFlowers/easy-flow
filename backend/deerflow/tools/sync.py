'''为同步代理调用路径执行异步工具提供桥接工具。'''

import asyncio
import atexit
import concurrent.futures
import contextvars
import functools
import logging
from collections.abc import Callable
from typing import Any, get_type_hints

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

# 在异步环境中调用同步工具时共用的线程池。
_SYNC_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="tool-sync")

atexit.register(lambda: _SYNC_TOOL_EXECUTOR.shutdown(wait=False))


def _get_runnable_config_param(func: Callable[..., Any]) -> str | None:
    '''返回协程中用于接收 LangChain ``RunnableConfig`` 的参数名。'''
    if isinstance(func, functools.partial):
        func = func.func

    try:
        type_hints = get_type_hints(func)
    except Exception:
        return None

    for name, type_ in type_hints.items():
        if type_ is RunnableConfig:
            return name
    return None


def make_sync_tool_wrapper(coro: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    '''为异步工具协程构建可供 ``BaseTool.func`` 使用的同步包装器。

    若协程声明了 ``RunnableConfig`` 参数，包装器会暴露 ``config`` 参数，
    以便 LangChain 注入运行时配置并转发给协程实际使用的配置参数。
    '''
    config_param = _get_runnable_config_param(coro)

    def run_coroutine(*args: Any, **kwargs: Any) -> Any:
        '''在当前线程或共享线程池中安全地等待协程完成。'''
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop is not None and loop.is_running():
                context = contextvars.copy_context()
                future = _SYNC_TOOL_EXECUTOR.submit(context.run, lambda: asyncio.run(coro(*args, **kwargs)))
                return future.result()
            return asyncio.run(coro(*args, **kwargs))
        except Exception as e:
            logger.error("Error invoking tool %r via sync wrapper: %s", tool_name, e, exc_info=True)
            raise

    if config_param:

        def sync_wrapper(*args: Any, config: RunnableConfig = None, **kwargs: Any) -> Any:
            '''转发参数，并在需要时注入运行时配置。'''
            if config is not None or config_param not in kwargs:
                kwargs[config_param] = config
            return run_coroutine(*args, **kwargs)

        return sync_wrapper

    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        '''转发参数并同步执行底层协程。'''
        return run_coroutine(*args, **kwargs)

    return sync_wrapper
