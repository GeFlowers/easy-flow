'''JWT 令牌的创建与验证。'''

from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel

from app.gateway.auth.config import get_auth_config
from app.gateway.auth.errors import TokenError


class TokenPayload(BaseModel):
    '''JWT 令牌负载。'''

    sub: str  # 用户标识
    exp: datetime
    iat: datetime | None = None
    ver: int = 0  # 令牌版本，必须与 User.token_version 一致


def create_access_token(user_id: str, expires_delta: timedelta | None = None, token_version: int = 0) -> str:
    '''为用户创建访问 JWT，并写入过期时间与令牌版本以支持失效控制。'''
    config = get_auth_config()
    expiry = expires_delta or timedelta(days=config.token_expiry_days)

    now = datetime.now(UTC)
    payload = {"sub": user_id, "exp": now + expiry, "iat": now, "ver": token_version}
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> TokenPayload | TokenError:
    '''解码并验证 JWT；成功返回负载，失败返回具体 ``TokenError``。'''
    config = get_auth_config()
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        return TokenError.EXPIRED
    except jwt.InvalidSignatureError:
        return TokenError.INVALID_SIGNATURE
    except jwt.PyJWTError:
        return TokenError.MALFORMED
