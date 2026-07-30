"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

from datetime import UTC, datetime, timedelta

import jwt as pyjwt

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError
from app.gateway.auth.jwt import create_access_token, decode_token


def test_auth_error_code_values():
    """验证“认证错误该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert AuthErrorCode.INVALID_CREDENTIALS == "invalid_credentials"
    assert AuthErrorCode.TOKEN_EXPIRED == "token_expired"
    assert AuthErrorCode.NOT_AUTHENTICATED == "not_authenticated"


def test_token_error_values():
    """验证“令牌错误该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert TokenError.EXPIRED == "expired"
    assert TokenError.INVALID_SIGNATURE == "invalid_signature"
    assert TokenError.MALFORMED == "malformed"


def test_auth_error_response_serialization():
    """验证“认证错误响应串行化”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    err = AuthErrorResponse(
        code=AuthErrorCode.TOKEN_EXPIRED,
        message="Token has expired",
    )
    d = err.model_dump()
    assert d == {"code": "token_expired", "message": "Token has expired"}


def test_auth_error_response_from_dict():
    """验证“认证错误响应该项字典”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    d = {"code": "invalid_credentials", "message": "Wrong password"}
    err = AuthErrorResponse(**d)
    assert err.code == AuthErrorCode.INVALID_CREDENTIALS


# ── 解码令牌类型失败测试 ──────────────────────────────

_TEST_SECRET = "test-secret-for-jwt-decode-token-tests"


def _setup_config():
    """为“设置配置”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))


def test_decode_token_returns_token_error_on_expired():
    """验证“解码令牌返回令牌错误该项过期”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    expired_payload = {"sub": "user-1", "exp": datetime.now(UTC) - timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(expired_payload, _TEST_SECRET, algorithm="HS256")
    result = decode_token(token)
    assert result == TokenError.EXPIRED


def test_decode_token_returns_token_error_on_bad_signature():
    """验证“解码令牌返回令牌错误该项该项签名”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    payload = {"sub": "user-1", "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
    result = decode_token(token)
    assert result == TokenError.INVALID_SIGNATURE


def test_decode_token_returns_token_error_on_malformed():
    """验证“解码令牌返回令牌错误该项格式错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    result = decode_token("not-a-jwt")
    assert result == TokenError.MALFORMED


def test_decode_token_returns_payload_on_valid():
    """验证“解码令牌返回负载该项有效”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    token = create_access_token("user-123")
    result = decode_token(token)
    assert not isinstance(result, TokenError)
    assert result.sub == "user-123"
