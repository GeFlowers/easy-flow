"定义 app_auth 模块提供的职责与可复用接口。\n\nGitHub App authentication helpers.\n\nThis module owns the two-stage auth dance GitHub Apps use:\n\n1. **App JWT** — signed with our App's RSA private key, lives 10 minutes\n   tops, identifies the App itself. Used only to mint installation\n   tokens.\n\n2. **Installation access token** — short-lived (1 hour) OAuth-style token\n   scoped to one installation (one customer org / one repo set). Used as\n   ``Authorization: token <…>`` on every REST call that does something\n   useful (post a comment, set a label, etc.).\n\nThe cache is in-process and intentionally simple: one dict keyed by\ninstallation id, with a 55-minute TTL so we refresh well before the\n60-minute GitHub limit. If two webhook deliveries land within a few\nseconds we'll mint two tokens — that's fine and well under any\nrate limit.\n"

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

logger = logging.getLogger(__name__)

# How long an App JWT lives. GitHub caps this at 10 minutes; we use 9 to
# leave headroom for the request itself.
_APP_JWT_TTL_SECONDS = 9 * 60
# Refresh installation tokens this many seconds before they expire.
_INSTALLATION_TOKEN_LEEWAY_SECONDS = 5 * 60

_APP_ID_ENV = "GITHUB_APP_ID"
_PRIVATE_KEY_PATH_ENV = "GITHUB_APP_PRIVATE_KEY_PATH"
_PRIVATE_KEY_ENV = "GITHUB_APP_PRIVATE_KEY"

_GITHUB_API_BASE = "https://api.github.com"


class GitHubAppAuthError(RuntimeError):
    '封装 GitHubAppAuthError 的状态、协作关系与公开操作。\n\nRaised when GitHub App credentials are missing or invalid.'


@dataclass
class _CachedToken:
    '封装 _CachedToken 的状态、协作关系与公开操作'
    token: str
    expires_at: float  # epoch seconds


_token_cache: dict[int, _CachedToken] = {}
# Per-installation locks so a cold mint for installation A does not block
# concurrent lookups (cache hits OR independent cold mints) for any other
# installation. A single process-wide lock would serialize the entire
# fleet behind one slow GitHub /access_tokens roundtrip; this map gives
# each installation its own ~hundreds-of-ms HTTPS critical section while
# letting unrelated installations proceed concurrently.
_install_locks: dict[int, asyncio.Lock] = {}
# Guards the _install_locks map itself — only held while we look up /
# insert the per-installation lock, never while we hold one.
_install_locks_lock = asyncio.Lock()


async def _lock_for(installation_id: int) -> asyncio.Lock:
    '执行 _lock_for 的明确职责，并返回与调用约定一致的结果。\n\nReturn the lock dedicated to ``installation_id``, creating on demand.'
    async with _install_locks_lock:
        lock = _install_locks.get(installation_id)
        if lock is None:
            lock = asyncio.Lock()
            _install_locks[installation_id] = lock
        return lock


def app_id() -> int:
    '执行 app_id 的明确职责，并返回与调用约定一致的结果。\n\nReturn the configured GitHub App id, or raise if unset.\n\n    Read fresh on every call so operators can rotate it without a process\n    restart.\n    '
    raw = os.environ.get(_APP_ID_ENV)
    if not raw:
        raise GitHubAppAuthError(f"{_APP_ID_ENV} is not set")
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise GitHubAppAuthError(f"{_APP_ID_ENV}={raw!r} is not an integer") from exc


def load_app_private_key() -> str:
    "加载并返回，并遵守 load_app_private_key 所表达的接口约束。\n\nReturn the App's RSA private key as a PEM string.\n\n    Reads from ``GITHUB_APP_PRIVATE_KEY`` (inline PEM) if set, else from\n    the path in ``GITHUB_APP_PRIVATE_KEY_PATH``. Inline takes precedence\n    so operators can roll a key by setting an env var instead of moving\n    files around in production.\n    "
    inline = os.environ.get(_PRIVATE_KEY_ENV)
    if inline and inline.strip():
        return inline

    path = os.environ.get(_PRIVATE_KEY_PATH_ENV)
    if not path:
        raise GitHubAppAuthError(f"Neither {_PRIVATE_KEY_ENV} nor {_PRIVATE_KEY_PATH_ENV} is set")
    p = Path(path).expanduser()
    if not p.exists():
        raise GitHubAppAuthError(f"{_PRIVATE_KEY_PATH_ENV} points to nonexistent file: {p}")
    return p.read_text(encoding="utf-8")


def mint_app_jwt(*, now: float | None = None) -> str:
    '执行 mint_app_jwt 的明确职责，并返回与调用约定一致的结果。\n\nSign a short-lived JWT identifying this App to GitHub.\n\n    Args:\n        now: Optional override for ``time.time()`` — tests use this.\n\n    Returns:\n        Signed RS256 JWT suitable for ``Authorization: Bearer <jwt>``.\n    '
    issued_at = int(now if now is not None else time.time())
    payload = {
        # GitHub recommends iat 60s in the past to tolerate clock skew.
        "iat": issued_at - 60,
        "exp": issued_at + _APP_JWT_TTL_SECONDS,
        # iss must be a string in current pyjwt; GitHub accepts the
        # numeric App id rendered as a decimal string.
        "iss": str(app_id()),
    }
    return jwt.encode(payload, load_app_private_key(), algorithm="RS256")


async def _request_new_installation_token(
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> _CachedToken:
    '执行 _request_new_installation_token 的明确职责，并返回与调用约定一致的结果。\n\nHit ``POST /app/installations/{id}/access_tokens`` once.'
    headers = {
        "Authorization": f"Bearer {mint_app_jwt()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{_GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"

    async def _do(c: httpx.AsyncClient) -> _CachedToken:
        '执行 _do 的明确职责，并返回与调用约定一致的结果'
        resp = await c.post(url, headers=headers, timeout=15.0)
        if resp.status_code != 201:
            raise GitHubAppAuthError(f"Failed to mint installation token (status={resp.status_code} body={resp.text!r})")
        data = resp.json()
        token = data["token"]
        # GitHub returns ISO8601 expires_at; we just bake in a 60-minute
        # life and let the leeway handle the rest. Trusting the wall
        # clock instead of parsing ISO is fine here.
        expires_at = time.time() + 60 * 60
        return _CachedToken(token=token, expires_at=expires_at)

    if client is None:
        async with httpx.AsyncClient() as c:
            return await _do(c)
    return await _do(client)


async def mint_installation_token(
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
    force_refresh: bool = False,
) -> str:
    "执行 mint_installation_token 的明确职责，并返回与调用约定一致的结果。\n\nReturn a valid installation access token, minting if necessary.\n\n    Concurrency: a per-installation :class:`asyncio.Lock` serializes mints\n    for the same installation (so two parallel cache-misses don't double-\n    mint), but mints for DIFFERENT installations proceed concurrently —\n    a slow GitHub /access_tokens call for installation A no longer\n    blocks lookups for installation B.\n\n    Cache hits take a lock-free fast path: we check the dict before\n    acquiring any lock, since :class:`asyncio.Lock` itself awaits the\n    event loop and there's no need to serialize a pure read on a value\n    that only this function ever mutates. The lock is re-acquired only\n    when we miss and need to mint, and we re-check the cache inside the\n    lock (double-checked locking) in case another coroutine just minted\n    while we were waiting.\n\n    Args:\n        installation_id: GitHub App installation id (per repo set).\n        client: Optional shared :class:`httpx.AsyncClient` — pass one in\n            if you have a long-lived client.\n        force_refresh: Skip the cache. Use after a 401 from the API.\n\n    Returns:\n        The token string. Caller adds ``Authorization: token <token>``.\n    "
    if installation_id <= 0:
        raise GitHubAppAuthError(f"installation_id must be positive, got {installation_id!r}")

    # Fast path: lock-free cache hit. The dict is mutated only inside
    # the per-installation lock below, and Python dict reads of an
    # existing key are atomic, so seeing a stale-but-still-valid entry
    # here is fine (it's the same logic as the locked check, just
    # earlier).
    if not force_refresh:
        cached = _token_cache.get(installation_id)
        if cached is not None and cached.expires_at - _INSTALLATION_TOKEN_LEEWAY_SECONDS > time.time():
            return cached.token

    lock = await _lock_for(installation_id)
    async with lock:
        # Double-check: another coroutine for the same installation may
        # have just minted while we were waiting for this lock.
        cached = _token_cache.get(installation_id)
        if cached is not None and not force_refresh and cached.expires_at - _INSTALLATION_TOKEN_LEEWAY_SECONDS > time.time():
            return cached.token

        fresh = await _request_new_installation_token(installation_id, client=client)
        _token_cache[installation_id] = fresh
        return fresh.token


def _clear_token_cache_for_tests() -> None:
    '执行 _clear_token_cache_for_tests 的明确职责，并返回与调用约定一致的结果。\n\nDrop every cached token. Tests reach for this between cases.'
    _token_cache.clear()
    _install_locks.clear()
