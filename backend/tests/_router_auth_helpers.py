'定义 _router_auth_helpers 模块提供的职责与可复用接口。\n\nHelpers for router-level tests that need a stubbed auth context.\n\nThe production gateway runs ``AuthMiddleware`` (validates the JWT cookie)\nahead of every router, plus ``@require_permission(owner_check=True)``\ndecorators that read ``request.state.auth`` and call\n``thread_store.check_access``. Router-level unit tests construct\n**bare** FastAPI apps that include only one router — they have neither\nthe auth middleware nor a real thread_store, so the decorators raise\n401 (TestClient path) or ValueError (direct-call path).\n\nThis module provides two surfaces:\n\n1. :func:`make_authed_test_app` — wraps ``FastAPI()`` with a tiny\n   ``BaseHTTPMiddleware`` that stamps a fake user / AuthContext on every\n   request, plus a permissive ``thread_store`` mock on\n   ``app.state``. Use from TestClient-based router tests.\n\n2. :func:`call_unwrapped` — invokes the underlying function bypassing\n   the ``@require_permission`` decorator chain by walking ``__wrapped__``.\n   Use from direct-call tests that previously imported the route\n   function and called it positionally.\n\nBoth helpers are deliberately permissive: they never deny a request.\nTests that want to verify the *auth boundary itself* (e.g.\n``test_auth_middleware``, ``test_auth_type_system``) build their own\napps with the real middleware — those should not use this module.\n'

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.gateway.auth.models import User
from app.gateway.authz import AuthContext, Permissions

# Default permission set granted to the stub user. Mirrors `_ALL_PERMISSIONS`
# in authz.py — kept inline so the tests don't import a private symbol.
_STUB_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
]


def _make_stub_user() -> User:
    '执行 _make_stub_user 的明确职责，并返回与调用约定一致的结果。\n\nA deterministic test user — same shape as production, fresh UUID.'
    return User(
        email="router-test@example.com",
        password_hash="x",
        system_role="user",
        id=uuid4(),
    )


class _StubAuthMiddleware(BaseHTTPMiddleware):
    '封装 _StubAuthMiddleware 的状态、协作关系与公开操作。\n\nStamp a fake user / AuthContext onto every request.\n\n    Mirrors what production ``AuthMiddleware`` does after the JWT decode\n    + DB lookup short-circuit, so ``@require_permission`` finds an\n    authenticated context and skips its own re-authentication path.\n    '

    def __init__(self, app: ASGIApp, user_factory: Callable[[], User]) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        super().__init__(app)
        self._user_factory = user_factory

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        '执行 dispatch 的明确职责，并返回与调用约定一致的结果'
        user = self._user_factory()
        request.state.user = user
        request.state.auth = AuthContext(user=user, permissions=list(_STUB_PERMISSIONS))
        return await call_next(request)


def make_authed_test_app(
    *,
    user_factory: Callable[[], User] | None = None,
    owner_check_passes: bool = True,
) -> FastAPI:
    '构造并返回，并遵守 make_authed_test_app 所表达的接口约束。\n\nBuild a FastAPI test app with stub auth + permissive thread_store.\n\n    Args:\n        user_factory: Override the default test user. Must return a fully\n            populated :class:`User`. Useful for cross-user isolation tests\n            that need a stable id across requests.\n        owner_check_passes: When True (default), ``thread_store.check_access``\n            returns True for every call so ``@require_permission(owner_check=True)``\n            never blocks the route under test. Pass False to verify that\n            permission failures surface correctly.\n\n    Returns:\n        A ``FastAPI`` app with the stub middleware installed and\n        ``app.state.thread_store`` set to a permissive mock. The\n        caller is still responsible for ``app.include_router(...)``.\n    '
    factory = user_factory or _make_stub_user
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, user_factory=factory)

    repo = MagicMock()
    repo.check_access = AsyncMock(return_value=owner_check_passes)
    app.state.thread_store = repo

    return app


def call_unwrapped[*P, R](decorated: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
    "执行 call_unwrapped 的明确职责，并返回与调用约定一致的结果。\n\nInvoke the underlying function of a ``@require_permission``-decorated route.\n\n    ``functools.wraps`` sets ``__wrapped__`` on each layer; we walk all\n    the way down to the original handler, bypassing every authz +\n    require_auth wrapper. Use from tests that need to call route\n    functions directly (without TestClient) and don't want to construct\n    a fake ``Request`` just to satisfy the decorator. The ``ParamSpec``\n    propagates the wrapped route's signature so call sites still get\n    parameter checking despite the unwrapping.\n    "
    fn: Callable = decorated
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__  # type: ignore[attr-defined]
    return fn(*args, **kwargs)
