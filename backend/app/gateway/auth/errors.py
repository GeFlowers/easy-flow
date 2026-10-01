'''认证模块使用的类型化错误定义。

``AuthErrorCode`` 枚举认证失败原因，``TokenError`` 枚举 JWT 解码失败原因，
``AuthErrorResponse`` 定义 HTTP 响应的结构化错误负载。
'''

from enum import StrEnum

from pydantic import BaseModel


class AuthErrorCode(StrEnum):
    '''完整列举认证失败状态。'''

    INVALID_CREDENTIALS = "invalid_credentials"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_INVALID = "token_invalid"
    USER_NOT_FOUND = "user_not_found"
    EMAIL_ALREADY_EXISTS = "email_already_exists"
    PROVIDER_NOT_FOUND = "provider_not_found"
    NOT_AUTHENTICATED = "not_authenticated"
    SYSTEM_ALREADY_INITIALIZED = "system_already_initialized"


class TokenError(StrEnum):
    '''完整列举 JWT 解码失败原因。'''

    EXPIRED = "expired"
    INVALID_SIGNATURE = "invalid_signature"
    MALFORMED = "malformed"


class AuthErrorResponse(BaseModel):
    '''用于替代裸 ``detail`` 字符串的结构化错误响应。'''

    code: AuthErrorCode
    message: str


def token_error_to_code(err: TokenError) -> AuthErrorCode:
    '''将 ``TokenError`` 映射为 ``AuthErrorCode`` 的唯一规则入口。'''
    if err == TokenError.EXPIRED:
        return AuthErrorCode.TOKEN_EXPIRED
    return AuthErrorCode.TOKEN_INVALID
