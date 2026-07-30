"定义 user_context 模块提供的职责与可复用接口。\n\nRequest-scoped user context for user-based authorization.\n\nThis module holds a :class:`~contextvars.ContextVar` that the gateway's\nauth middleware sets after a successful authentication. Repository\nmethods read the contextvar via a sentinel default parameter, letting\nrouters stay free of ``user_id`` boilerplate.\n\nThree-state semantics for the repository ``user_id`` parameter (the\nconsumer side of this module lives in ``deerflow.persistence.*``):\n\n- ``_AUTO`` (module-private sentinel, default): read from contextvar;\n  raise :class:`RuntimeError` if unset.\n- Explicit ``str``: use the provided value, overriding contextvar.\n- Explicit ``None``: no WHERE clause — used only by migration scripts\n  and admin CLIs that intentionally bypass isolation.\n\nDependency direction\n--------------------\n``persistence`` (lower layer) reads from this module; ``gateway.auth``\n(higher layer) writes to it. ``CurrentUser`` is defined here as a\n:class:`typing.Protocol` so that ``persistence`` never needs to import\nthe concrete ``User`` class from ``gateway.auth.models``. Any object\nwith an ``.id: str`` attribute structurally satisfies the protocol.\n\nAsyncio semantics\n-----------------\n``ContextVar`` is task-local under asyncio, not thread-local. Each\nFastAPI request runs in its own task, so the context is naturally\nisolated. ``asyncio.create_task`` and ``asyncio.to_thread`` inherit the\nparent task's context, which is typically the intended behaviour; if\na background task must *not* see the foreground user, wrap it with\n``contextvars.copy_context()`` to get a clean copy.\n"

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Final, Protocol, runtime_checkable


@runtime_checkable
class CurrentUser(Protocol):
    '封装 CurrentUser 的状态、协作关系与公开操作。\n\nStructural type for the current authenticated user.\n\n    Any object with an ``.id: str`` attribute satisfies this protocol.\n    Concrete implementations live in ``app.gateway.auth.models.User``.\n    '

    id: str


_current_user: Final[ContextVar[CurrentUser | None]] = ContextVar("deerflow_current_user", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    '执行 set_current_user 的明确职责，并返回与调用约定一致的结果。\n\nSet the current user for this async task.\n\n    Returns a reset token that should be passed to\n    :func:`reset_current_user` in a ``finally`` block to restore the\n    previous context.\n    '
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    '执行 reset_current_user 的明确职责，并返回与调用约定一致的结果。\n\nRestore the context to the state captured by ``token``.'
    _current_user.reset(token)


def get_current_user() -> CurrentUser | None:
    '读取并返回，并遵守 get_current_user 所表达的接口约束。\n\nReturn the current user, or ``None`` if unset.\n\n    Safe to call in any context. Used by code paths that can proceed\n    without a user (e.g. migration scripts, public endpoints).\n    '
    return _current_user.get()


def require_current_user() -> CurrentUser:
    '执行 require_current_user 的明确职责，并返回与调用约定一致的结果。\n\nReturn the current user, or raise :class:`RuntimeError`.\n\n    Used by repository code that must not be called outside a\n    request-authenticated context. The error message is phrased so\n    that a caller debugging a stack trace can locate the offending\n    code path.\n    '
    user = _current_user.get()
    if user is None:
        raise RuntimeError("repository accessed without user context")
    return user


# ---------------------------------------------------------------------------
# Effective user_id helpers (filesystem isolation)
# ---------------------------------------------------------------------------

DEFAULT_USER_ID: Final[str] = "default"


def get_effective_user_id() -> str:
    "读取并返回，并遵守 get_effective_user_id 所表达的接口约束。\n\nReturn the current user's id as a string, or DEFAULT_USER_ID if unset.\n\n    Unlike :func:`require_current_user` this never raises — it is designed\n    for filesystem-path resolution where a valid user bucket is always needed.\n    "
    user = _current_user.get()
    if user is None:
        return DEFAULT_USER_ID
    return str(user.id)


def resolve_runtime_user_id(runtime: object | None) -> str:
    '执行 resolve_runtime_user_id 的明确职责，并返回与调用约定一致的结果。\n\nSingle source of truth for a tool/middleware\'s effective user_id.\n\n    Resolution order (most authoritative first):\n      1. ``runtime.context["user_id"]`` — set by ``inject_authenticated_user_context``\n         in the gateway from the auth-validated ``request.state.user``. This is\n         the only source that survives boundaries where the contextvar may have\n         been lost (background tasks scheduled outside the request task,\n         worker pools that don\'t copy_context, future cross-process drivers).\n      2. The ``_current_user`` ContextVar — set by the auth middleware at\n         request entry. Reliable for in-task work; copied by ``asyncio``\n         child tasks and by ``ContextThreadPoolExecutor``.\n      3. ``DEFAULT_USER_ID`` — last-resort fallback so unauthenticated\n         CLI / migration / test paths keep working without raising.\n\n    Tools that persist user-scoped state (custom agents, memory, uploads)\n    MUST call this instead of ``get_effective_user_id()`` directly so they\n    benefit from the runtime.context channel that ``setup_agent`` already\n    relies on.\n    '
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_user_id()


# ---------------------------------------------------------------------------
# Sentinel-based user_id resolution
# ---------------------------------------------------------------------------
#
# Repository methods accept a ``user_id`` keyword-only argument that
# defaults to ``AUTO``. The three possible values drive distinct
# behaviours; see the docstring on :func:`resolve_user_id`.


class _AutoSentinel:
    "封装 _AutoSentinel 的状态、协作关系与公开操作。\n\nSingleton marker meaning 'resolve user_id from contextvar'."

    _instance: _AutoSentinel | None = None

    def __new__(cls) -> _AutoSentinel:
        '实现 __new__ 协议方法，保持对象交互语义一致'
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        '实现 __repr__ 协议方法，保持对象交互语义一致'
        return "<AUTO>"


AUTO: Final[_AutoSentinel] = _AutoSentinel()


def resolve_user_id(
    value: str | None | _AutoSentinel,
    *,
    method_name: str = "repository method",
) -> str | None:
    '执行 resolve_user_id 的明确职责，并返回与调用约定一致的结果。\n\nResolve the user_id parameter passed to a repository method.\n\n    Three-state semantics:\n\n    - :data:`AUTO` (default): read from contextvar; raise\n      :class:`RuntimeError` if no user is in context. This is the\n      common case for request-scoped calls.\n    - Explicit ``str``: use the provided id verbatim, overriding any\n      contextvar value. Useful for tests and admin-override flows.\n    - Explicit ``None``: no filter — the repository should skip the\n      user_id WHERE clause entirely. Reserved for migration scripts\n      and CLI tools that intentionally bypass isolation.\n    '
    if isinstance(value, _AutoSentinel):
        user = _current_user.get()
        if user is None:
            raise RuntimeError(f"{method_name} called with user_id=AUTO but no user context is set; pass an explicit user_id, set the contextvar via auth middleware, or opt out with user_id=None for migration/CLI paths.")
        # Coerce to ``str`` at the boundary: ``User.id`` is typed as
        # ``UUID`` for the API surface, but the persistence layer
        # stores ``user_id`` as ``String(64)`` and aiosqlite cannot
        # bind a raw UUID object to a VARCHAR column ("type 'UUID' is
        # not supported"). Honour the documented return type here
        # rather than ripple a type change through every caller.
        return str(user.id)
    return value
