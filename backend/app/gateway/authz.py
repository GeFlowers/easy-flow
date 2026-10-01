'''DeerFlow 的授权装饰器与请求认证上下文。

路由可使用 ``@require_auth`` 要求认证，并使用
``@require_permission("资源", "操作", ...)`` 检查权限；装饰器链由下至上处理。
权限包括线程的读写删及运行的创建、读取和取消。
'''

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from app.gateway.auth.models import User

P = ParamSpec("P")
T = TypeVar("T")


# 权限常量
class Permissions:
    '''使用 ``资源:操作`` 格式表示的权限常量。'''

    # 线程
    THREADS_READ = "threads:read"
    THREADS_WRITE = "threads:write"
    THREADS_DELETE = "threads:delete"

    # 运行
    RUNS_CREATE = "runs:create"
    RUNS_READ = "runs:read"
    RUNS_CANCEL = "runs:cancel"


class AuthContext:
    '''当前请求的认证上下文，由认证装饰器写入 ``request.state.auth``。'''

    __slots__ = ("user", "permissions")

    def __init__(self, user: User | None = None, permissions: list[str] | None = None):
        '''使用已认证用户及其权限集合初始化请求上下文。'''
        self.user = user
        self.permissions = permissions or []

    @property
    def is_authenticated(self) -> bool:
        '''判断上下文中是否存在已认证用户。'''
        return self.user is not None

    def has_permission(self, resource: str, action: str) -> bool:
        '''判断上下文是否拥有指定资源操作的权限。'''
        permission = f"{resource}:{action}"
        return permission in self.permissions

    def require_user(self) -> User:
        '''返回已认证用户；不存在时抛出 401。'''
        if not self.user:
            raise HTTPException(status_code=401, detail="Authentication required")
        return self.user


def get_auth_context(request: Request) -> AuthContext | None:
    '''从请求状态取得认证上下文。'''
    return getattr(request.state, "auth", None)


_ALL_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
]


def _make_test_request_stub() -> Any:
    '''为直接单元调用创建最小请求对象，包含认证辅助函数访问的字段。'''
    return SimpleNamespace(state=SimpleNamespace(), cookies={}, _deerflow_test_bypass_auth=True)


async def _authenticate(request: Request) -> AuthContext:
    '''认证请求并返回认证上下文；匿名请求的 ``user`` 为 ``None``。'''
    from app.gateway.deps import get_optional_user_from_request

    user = await get_optional_user_from_request(request)
    if user is None:
        return AuthContext(user=None, permissions=[])

    # 未来可将权限存储在用户记录中。
    return AuthContext(user=user, permissions=_ALL_PERMISSIONS)


def require_auth[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    '''认证请求并强制要求已认证，与 ASGI 栈是否安装认证中间件无关。

    将解析出的 ``AuthContext`` 写入 ``request.state.auth`` 供下游使用；该装饰器
    必须置于其他装饰器之上。未认证时抛出 401，缺少 ``request`` 参数时抛出 ValueError。
    '''

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        '''补齐测试请求、认证调用方并执行被装饰的处理器。'''
        request = kwargs.get("request")
        if request is None:
            # 单元测试可直接调用已装饰处理器而不构造请求对象；被包装函数声明请求
            # 参数时注入最小请求替身。
            if "request" in inspect.signature(func).parameters:
                kwargs["request"] = _make_test_request_stub()
            else:
                raise ValueError("require_auth decorator requires 'request' parameter")
            request = kwargs["request"]

        if getattr(request, "_deerflow_test_bypass_auth", False):
            return await func(*args, **kwargs)

        # 完成认证并写入请求上下文。
        auth_context = await _authenticate(request)
        request.state.auth = auth_context

        if not auth_context.is_authenticated:
            raise HTTPException(status_code=401, detail="Authentication required")

        return await func(*args, **kwargs)

    return wrapper


def require_permission(
    resource: str,
    action: str,
    owner_check: bool = False,
    require_existing: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    '''创建检查 ``资源:操作`` 权限的装饰器，必须用于 ``@require_auth`` 之后。

    ``owner_check`` 会验证调用者拥有 ``thread_id`` 指定资源；在破坏性或修改性路由上
    设置 ``require_existing``，使缺失的 ``threads_meta`` 行按 404 拒绝，防止其他用户
    经缺行路径重新定位已删除线程。
    '''

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        '''为具体路由处理器创建权限检查包装器。'''

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            '''认证调用方、检查权限及资源归属后执行处理器。'''
            request = kwargs.get("request")
            if request is None:
                # 单元测试可直接调用路由处理器而不构造请求对象；被包装函数声明请求
                # 参数时注入最小替身。
                if "request" in inspect.signature(func).parameters:
                    kwargs["request"] = _make_test_request_stub()
                else:
                    return await func(*args, **kwargs)
                request = kwargs["request"]

            if getattr(request, "_deerflow_test_bypass_auth", False):
                return await func(*args, **kwargs)

            auth: AuthContext = getattr(request.state, "auth", None)
            if auth is None:
                auth = await _authenticate(request)
                request.state.auth = auth

            if not auth.is_authenticated:
                raise HTTPException(status_code=401, detail="Authentication required")

            # 检查资源操作权限。
            if not auth.has_permission(resource, action):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {resource}:{action}",
                )

            # 检查线程专属资源的所有权。候选版已将线程元数据迁入持久化层；访问检查
            # 对缺失行（未跟踪的旧线程）及所有者为空的行（共享或认证前数据）允许访问，
            # 因而只有已存在且所有者不同的行会触发严格拒绝的 404。
            if owner_check:
                from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE

                thread_id = kwargs.get("thread_id")
                if thread_id is None:
                    raise ValueError("require_permission with owner_check=True requires 'thread_id' parameter")

                from app.gateway.deps import get_thread_store

                thread_store = get_thread_store(request)
                allowed = await thread_store.check_access(
                    thread_id,
                    str(auth.user.id),
                    require_existing=require_existing,
                )
                if not allowed and getattr(auth.user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
                    # 可信内部调用方（频道工作进程）也代表头部中携带的连接所有者执行。
                    # 必须以该所有者的范围检查而非绕过检查，泄漏的内部令牌不得授予跨用户
                    # 线程访问。仅在认证状态已验证内部令牌后信任该头部，与基于中间件
                    # 写入用户状态的可信所有者解析规则一致。
                    header_owner = (request.headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME) or "").strip()
                    if header_owner:
                        allowed = await thread_store.check_access(
                            thread_id,
                            header_owner,
                            require_existing=require_existing,
                        )
                if not allowed:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Thread {thread_id} not found",
                    )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
