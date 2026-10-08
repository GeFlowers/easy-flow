'''

保存用于用户授权的请求范围用户上下文。

本模块维护一个 :class:`~contextvars.ContextVar`。网关认证中间件在认证
成功后写入它，持久化层通过哨兵默认参数读取它，路由层因此不必重复传递
``user_id``。

持久化层 ``user_id`` 参数有三种语义：

 - ``_AUTO``（模块私有哨兵，默认值）：从上下文读取，未设置时抛出
   :class:`RuntimeError`。
 - 显式 ``str``：使用传入值并覆盖上下文值。
 - 显式 ``None``：不添加 WHERE 条件，仅供有意绕过隔离的迁移脚本和管理命令使用。

依赖方向
--------
下层 ``persistence`` 从本模块读取上下文，上层 ``gateway.auth`` 写入上下文。
``CurrentUser`` 在此定义为 :class:`typing.Protocol`，使 ``persistence``
无需从 ``gateway.auth.models`` 导入具体的 ``User`` 类。
任何具有 ``.id: str`` 属性的对象都在结构上满足此协议。

asyncio 语义
-----------
在 asyncio 中，``ContextVar`` 的作用域是任务，而非线程。
每个 FastAPI 请求在独立任务中执行，因此上下文自然隔离。
``asyncio.create_task`` 和 ``asyncio.to_thread`` 会继承父任务上下文，
通常符合预期；若后台任务不应访问前台用户，应在独立上下文中启动它。
``contextvars.copy_context()`` 会复制当前上下文，使用该副本时仍需清除用户状态。
'''

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Final, Protocol, runtime_checkable


@runtime_checkable
class CurrentUser(Protocol):
    '''

    当前认证用户的结构化类型。

        任何具有 ``.id: str`` 属性的对象都满足此协议；具体实现位于
        ``app.gateway.auth.models.User``。
    '''

    id: str


_current_user: Final[ContextVar[CurrentUser | None]] = ContextVar("deerflow_current_user", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    '''

    为当前异步任务设置用户。

        返回一个重置令牌，调用方应在 ``finally`` 中将其传给
        :func:`reset_current_user`，以恢复之前的上下文。
    '''
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    '''

    将上下文恢复为 ``token`` 捕获的状态。'''
    _current_user.reset(token)


def get_current_user() -> CurrentUser | None:
    '''

    返回当前用户；未设置时返回 ``None``。

        可在任意上下文调用，适用于迁移脚本和公开接口等允许无用户的路径。
    '''
    return _current_user.get()


def require_current_user() -> CurrentUser:
    '''

    返回当前用户；没有用户上下文时抛出 :class:`RuntimeError`。

        供必须运行在已认证请求中的持久化代码使用，错误信息包含调用路径定位线索。
    '''
    user = _current_user.get()
    if user is None:
        raise RuntimeError("repository accessed without user context")
    return user



DEFAULT_USER_ID: Final[str] = "default"


def get_effective_user_id() -> str:
    '''

    返回当前用户的字符串 ID；未设置时返回 DEFAULT_USER_ID。

        与 :func:`require_current_user` 不同，本函数不会抛出异常，专门用于始终需要
        有效用户目录的文件系统路径解析。
    '''
    user = _current_user.get()
    if user is None:
        return DEFAULT_USER_ID
    return str(user.id)


def resolve_runtime_user_id(runtime: object | None) -> str:
    '''

    解析工具或中间件有效 user_id 的唯一入口。

        解析顺序（优先级从高到低）：
          1. ``runtime.context["user_id"]`` — 网关通过 ``inject_authenticated_user_context``
             从已认证的 ``request.state.user`` 设置此值。当上下文变量在边界处丢失时
             （如在请求任务之外调度的后台任务、不复制上下文的工作池，以及未来的
             跨进程驱动器），它是唯一仍可传递的用户来源。
          2. ``_current_user`` ContextVar — 认证中间件在请求入口设置；
             对任务内工作可靠，并由 ``asyncio`` 子任务及
             ``ContextThreadPoolExecutor`` 复制。
          3. ``DEFAULT_USER_ID`` — 最终回退值，使未认证的命令行、迁移和测试路径
             仍能正常运行而不抛出异常。

        保存用户范围状态的工具（自定义智能体、记忆、上传）必须调用本函数，
        以使用 setup_agent 依赖的 runtime.context 通道。
    '''
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_user_id()




class _AutoSentinel:
    '''

    表示“从 ContextVar 解析 user_id”的单例标记。'''

    _instance: _AutoSentinel | None = None

    def __new__(cls) -> _AutoSentinel:
        '''确保 AUTO 标记全局只存在一个实例，以区分参数未传入的情况。'''
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        '''返回稳定的标记名称，便于调试用户作用域解析。'''
        return "<AUTO>"


AUTO: Final[_AutoSentinel] = _AutoSentinel()


def resolve_user_id(
    value: str | None | _AutoSentinel,
    *,
    method_name: str = "repository method",
) -> str | None:
    '''

    解析传给持久化方法的 user_id 参数。

        三种取值语义：

        - :data:`AUTO`（默认）：从上下文读取；没有用户时抛出
          :class:`RuntimeError`，这是请求范围调用的常规路径。
        - 显式 ``str``：原样使用传入 ID，适合测试和管理员覆盖流程。
        - 显式 ``None``：不添加 user_id 过滤，仅供有意绕过隔离的迁移脚本和命令行工具使用。
    '''
    if isinstance(value, _AutoSentinel):
        user = _current_user.get()
        if user is None:
            raise RuntimeError(f"{method_name} called with user_id=AUTO but no user context is set; pass an explicit user_id, set the contextvar via auth middleware, or opt out with user_id=None for migration/CLI paths.")
        return str(user.id)
    return value
