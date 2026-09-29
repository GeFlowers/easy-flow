"""负责 GitHub App JWT 签发、安装令牌换取及按安装 ID 的短期令牌缓存。"""

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

# GitHub App JWT 最长有效期为 10 分钟；本实现留出请求传输余量。
_APP_JWT_TTL_SECONDS = 9 * 60
# 安装令牌在到期前预留此时长刷新。
_INSTALLATION_TOKEN_LEEWAY_SECONDS = 5 * 60

_APP_ID_ENV = "GITHUB_APP_ID"
_PRIVATE_KEY_PATH_ENV = "GITHUB_APP_PRIVATE_KEY_PATH"
_PRIVATE_KEY_ENV = "GITHUB_APP_PRIVATE_KEY"

_GITHUB_API_BASE = "https://api.github.com"


class GitHubAppAuthError(RuntimeError):
    """GitHub App 凭据缺失、格式错误或令牌交换失败时抛出的异常。"""


@dataclass
class _CachedToken:
    """保存安装访问令牌及其本地缓存失效时间。"""

    token: str
    expires_at: float  # epoch seconds


_token_cache: dict[int, _CachedToken] = {}
# 每个安装分别加锁，避免某个 GitHub 请求拖慢其他安装的缓存读取或令牌刷新。
_install_locks: dict[int, asyncio.Lock] = {}
# 仅保护安装锁映射的查找和插入，不会在持有某个安装锁期间继续占用。
_install_locks_lock = asyncio.Lock()


async def _lock_for(installation_id: int) -> asyncio.Lock:
    """获取指定安装的互斥锁；不存在时创建，避免不同安装互相阻塞。"""
    async with _install_locks_lock:
        lock = _install_locks.get(installation_id)
        if lock is None:
            lock = asyncio.Lock()
            _install_locks[installation_id] = lock
        return lock


def app_id() -> int:
    """从环境变量读取 GitHub App ID 并转换为整数，每次调用均读取最新值。"""
    raw = os.environ.get(_APP_ID_ENV)
    if not raw:
        raise GitHubAppAuthError(f"{_APP_ID_ENV} is not set")
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise GitHubAppAuthError(f"{_APP_ID_ENV}={raw!r} is not an integer") from exc


def load_app_private_key() -> str:
    """优先从环境变量读取内联 PEM 私钥，否则读取私钥路径指定的文件。"""
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
    """用 App 私钥签发短期 RS256 JWT，供 GitHub App 接口认证使用。"""
    issued_at = int(now if now is not None else time.time())
    payload = {
        # 将签发时间回拨 60 秒，容忍服务器时钟偏差。
        "iat": issued_at - 60,
        "exp": issued_at + _APP_JWT_TTL_SECONDS,
        # 当前 PyJWT 要求 iss 为字符串；GitHub 接受十进制文本形式的 App ID。
        "iss": str(app_id()),
    }
    return jwt.encode(payload, load_app_private_key(), algorithm="RS256")


async def _request_new_installation_token(
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> _CachedToken:
    """向 GitHub 请求新的安装访问令牌，并计算本地缓存到期时间。"""
    headers = {
        "Authorization": f"Bearer {mint_app_jwt()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{_GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"

    async def _do(c: httpx.AsyncClient) -> _CachedToken:
        """使用给定 HTTP 客户端发送令牌交换请求并解析响应。"""
        resp = await c.post(url, headers=headers, timeout=15.0)
        if resp.status_code != 201:
            raise GitHubAppAuthError(f"Failed to mint installation token (status={resp.status_code} body={resp.text!r})")
        data = resp.json()
        token = data["token"]
        # GitHub 返回 ISO8601 expires_at；此处按一小时有效期估算，再由刷新余量提前失效。
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
    """返回未过期的安装令牌；缓存未命中时按安装 ID 加锁并向 GitHub 换取。"""
    if installation_id <= 0:
        raise GitHubAppAuthError(f"installation_id must be positive, got {installation_id!r}")

    # 缓存读取快速路径无需加锁；有效的旧令牌仍可安全返回。
    if not force_refresh:
        cached = _token_cache.get(installation_id)
        if cached is not None and cached.expires_at - _INSTALLATION_TOKEN_LEEWAY_SECONDS > time.time():
            return cached.token

    lock = await _lock_for(installation_id)
    async with lock:
        # 等待互斥锁期间可能已有协程刷新令牌，因此再次检查缓存。
        cached = _token_cache.get(installation_id)
        if cached is not None and not force_refresh and cached.expires_at - _INSTALLATION_TOKEN_LEEWAY_SECONDS > time.time():
            return cached.token

        fresh = await _request_new_installation_token(installation_id, client=client)
        _token_cache[installation_id] = fresh
        return fresh.token


def _clear_token_cache_for_tests() -> None:
    """清空令牌和安装锁缓存，供测试隔离不同用例的状态。"""
    _token_cache.clear()
    _install_locks.clear()
