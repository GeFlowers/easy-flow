'''路由的认证和线程归属校验。'''

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from fastapi import HTTPException

from server.gateway.deps import get_optional_user_from_request, get_thread_store
from server.gateway.internal_auth import get_trusted_internal_owner_user_id

P = ParamSpec("P")
T = TypeVar("T")


def require_auth(
    *,
    owner_check: bool = False,
    require_existing: bool = False,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    '''要求认证，可同时核对路径参数指定的线程归属。

    需要既有线程元数据的操作通过 ``require_existing`` 对缺失记录返回 404。
    '''

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            request = kwargs.get("request")
            if request is None:
                raise ValueError("require_auth requires a 'request' parameter")

            user = await get_optional_user_from_request(request)
            if user is None:
                raise HTTPException(status_code=401, detail="Authentication required")

            if owner_check:
                thread_id = kwargs.get("thread_id")
                if thread_id is None:
                    raise ValueError("require_auth with owner_check=True requires a 'thread_id' parameter")

                thread_store = get_thread_store(request)
                allowed = await thread_store.check_access(
                    thread_id,
                    str(user.id),
                    require_existing=require_existing,
                )
                if not allowed:
                    # 频道内部请求也可用经验证的原始绑定所有者检查旧线程归属。
                    header_owner = get_trusted_internal_owner_user_id(request)
                    if header_owner:
                        allowed = await thread_store.check_access(
                            thread_id,
                            header_owner,
                            require_existing=require_existing,
                        )
                if not allowed:
                    raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

            return await func(*args, **kwargs)

        return wrapper

    return decorator
