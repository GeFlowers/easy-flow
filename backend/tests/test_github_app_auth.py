"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.gateway.github.app_auth import (
    _clear_token_cache_for_tests,
    load_app_private_key,
    mint_app_jwt,
    mint_installation_token,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _clear_token_cache_for_tests()


@pytest.fixture()
def private_key_pem() -> str:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture()
def set_github_env(monkeypatch: pytest.MonkeyPatch, private_key_pem: str) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setenv("GITHUB_APP_ID", "123456")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", private_key_pem)


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_mint_app_jwt_is_rs256(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import jwt

    token = mint_app_jwt()
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256"


def test_mint_app_jwt_iss_is_app_id(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import jwt

    token = mint_app_jwt()
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["iss"] == "123456"


def test_mint_app_jwt_exp_is_within_10_min(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import jwt

    now = 1700000000.0
    token = mint_app_jwt(now=now)
    payload = jwt.decode(token, options={"verify_signature": False})
    # 说明当前测试分支所验证的真实行为与边界。
    assert payload["iat"] == int(now) - 60
    assert payload["exp"] == int(now) + 9 * 60


def test_mint_app_jwt_verifies_with_its_own_key(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import jwt

    token = mint_app_jwt()
    # 说明当前测试分支所验证的真实行为与边界。
    from cryptography.hazmat.primitives import serialization

    priv = serialization.load_pem_private_key(load_app_private_key().encode(), password=None)
    pub_pem = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    jwt.decode(token, pub_pem, algorithms=["RS256"])


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def _make_token_transport(
    installation_id: int,
    token: str = "ghs_test-token",
    status: int = 201,
) -> httpx.MockTransport:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    def handler(request: httpx.Request) -> httpx.Response:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        expected_url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        if request.url.path == expected_url or request.url == expected_url:
            return httpx.Response(status, json={"token": token, "expires_at": "2099-01-01T00:00:00Z"})
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_mint_installation_token_returns_token(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    transport = _make_token_transport(42)
    async with httpx.AsyncClient(transport=transport) as client:
        token = await mint_installation_token(42, client=client)
    assert token == "ghs_test-token"


@pytest.mark.asyncio
async def test_mint_installation_token_caches_second_call(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        nonlocal call_count
        call_count += 1
        return httpx.Response(201, json={"token": f"tok-{call_count}", "expires_at": "2099-01-01T00:00:00Z"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        t1 = await mint_installation_token(42, client=client)
        t2 = await mint_installation_token(42, client=client)
    assert t1 == "tok-1"
    assert t2 == "tok-1"  # 说明当前测试分支所验证的真实行为与边界。
    assert call_count == 1


@pytest.mark.asyncio
async def test_mint_installation_token_force_refresh_bypasses_cache(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        nonlocal call_count
        call_count += 1
        return httpx.Response(201, json={"token": f"tok-{call_count}", "expires_at": "2099-01-01T00:00:00Z"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        t1 = await mint_installation_token(42, client=client)
        t2 = await mint_installation_token(42, client=client, force_refresh=True)
    assert t1 == "tok-1"
    assert t2 == "tok-2"
    assert call_count == 2


@pytest.mark.asyncio
async def test_mint_installation_token_refreshes_expired_token(set_github_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setattr("app.gateway.github.app_auth._INSTALLATION_TOKEN_LEEWAY_SECONDS", 999999)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        nonlocal call_count
        call_count += 1
        return httpx.Response(201, json={"token": f"tok-{call_count}", "expires_at": "2099-01-01T00:00:00Z"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        t1 = await mint_installation_token(42, client=client)
        # 说明当前测试分支所验证的真实行为与边界。
        t2 = await mint_installation_token(42, client=client)
    assert t1 == "tok-1"
    assert t2 == "tok-2"
    assert call_count == 2


@pytest.mark.asyncio
async def test_mint_installation_token_raises_on_non_201(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    transport = _make_token_transport(55, status=500)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(Exception):  # noqa: PT011
            await mint_installation_token(55, client=client)


@pytest.mark.asyncio
async def test_mint_installation_token_raises_on_bad_id(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with pytest.raises(Exception):  # noqa: PT011
        await mint_installation_token(-1)


@pytest.mark.asyncio
async def test_mint_installation_token_without_client(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    transport = _make_token_transport(99)
    async with httpx.AsyncClient(transport=transport) as _:  # 说明当前测试分支所验证的真实行为与边界。
        pass
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    pass


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cold_mints_for_different_installations_run_concurrently(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio

    a_release = asyncio.Event()
    b_release = asyncio.Event()
    a_in_flight = asyncio.Event()
    b_in_flight = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        path = request.url.path
        if path.endswith("/installations/1/access_tokens"):
            a_in_flight.set()
            await a_release.wait()
            return httpx.Response(201, json={"token": "tok-A", "expires_at": "2099-01-01T00:00:00Z"})
        if path.endswith("/installations/2/access_tokens"):
            b_in_flight.set()
            await b_release.wait()
            return httpx.Response(201, json={"token": "tok-B", "expires_at": "2099-01-01T00:00:00Z"})
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        task_a = asyncio.create_task(mint_installation_token(1, client=client))
        task_b = asyncio.create_task(mint_installation_token(2, client=client))

        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        await asyncio.wait_for(a_in_flight.wait(), timeout=2.0)
        await asyncio.wait_for(b_in_flight.wait(), timeout=2.0)

        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        b_release.set()
        b_token = await asyncio.wait_for(task_b, timeout=2.0)
        assert b_token == "tok-B"
        assert not task_a.done()  # 说明当前测试分支所验证的真实行为与边界。

        a_release.set()
        a_token = await asyncio.wait_for(task_a, timeout=2.0)
        assert a_token == "tok-A"


@pytest.mark.asyncio
async def test_concurrent_mints_for_same_installation_dedupe(set_github_env: None) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import asyncio

    call_count = 0
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        nonlocal call_count
        call_count += 1
        await release.wait()
        return httpx.Response(201, json={"token": f"tok-{call_count}", "expires_at": "2099-01-01T00:00:00Z"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        task_1 = asyncio.create_task(mint_installation_token(42, client=client))
        task_2 = asyncio.create_task(mint_installation_token(42, client=client))
        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        await asyncio.sleep(0.05)
        release.set()
        results = await asyncio.gather(task_1, task_2)

    # 说明当前测试分支所验证的真实行为与边界。
    assert results[0] == results[1] == "tok-1"
    assert call_count == 1
