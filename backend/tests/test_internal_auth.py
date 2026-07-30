"""覆盖本文件的鉴权或中断序列化回归边界。"""

from __future__ import annotations

import importlib


def test_internal_auth_uses_shared_env_token(monkeypatch):
    """验证既有契约在返回结构、异常传播或资源隔离变化时明确失败。"""
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers()

        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "shared-token"
        assert reloaded.is_valid_internal_auth_token("shared-token") is True
        assert reloaded.is_valid_internal_auth_token("other-token") is False
    finally:
        monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
        importlib.reload(reloaded)


def test_internal_auth_generates_process_local_fallback(monkeypatch):
    """验证既有契约在返回结构、异常传播或资源隔离变化时明确失败。"""
    import app.gateway.internal_auth as internal_auth

    monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
    reloaded = importlib.reload(internal_auth)
    try:
        token = reloaded.create_internal_auth_headers()[reloaded.INTERNAL_AUTH_HEADER_NAME]

        assert token
        assert reloaded.is_valid_internal_auth_token(token) is True
    finally:
        importlib.reload(reloaded)


def test_internal_auth_headers_can_carry_owner_user_id(monkeypatch):
    """验证既有契约在返回结构、异常传播或资源隔离变化时明确失败。"""
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers(owner_user_id="owner-1")

        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "shared-token"
        assert headers[reloaded.INTERNAL_OWNER_USER_ID_HEADER_NAME] == "owner-1"
    finally:
        monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
        importlib.reload(reloaded)


def test_get_internal_user_normalises_unsafe_owner_user_id():
    """验证既有契约在返回结构、异常传播或资源隔离变化时明确失败。"""
    import app.gateway.internal_auth as internal_auth
    from deerflow.config.paths import make_safe_user_id

    # 此处固定序列化或鉴权边界，避免回归退化为不可验证状态。
    user_a = internal_auth.get_internal_user(owner_user_id="ou_abc/../../etc/passwd")
    user_b = internal_auth.get_internal_user(owner_user_id="ou_abc/../../etc/passwd")
    assert user_a.id == user_b.id
    assert "/" not in user_a.id
    assert ".." not in user_a.id

    # 此处固定序列化或鉴权边界，避免回归退化为不可验证状态。
    user_neg = internal_auth.get_internal_user(owner_user_id="-1001234567890:alice")
    assert user_neg.id == make_safe_user_id("-1001234567890:alice")
    assert ":" not in user_neg.id
    assert user_neg.system_role == "internal"

    # 此处固定序列化或鉴权边界，避免回归退化为不可验证状态。
    user_safe = internal_auth.get_internal_user(owner_user_id="alice_42")
    assert user_safe.id == "alice_42"

    # 此处固定序列化或鉴权边界，避免回归退化为不可验证状态。
    assert internal_auth.get_internal_user().id == "default"
    assert internal_auth.get_internal_user(owner_user_id="").id == "default"
