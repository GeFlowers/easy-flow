'''认证流程使用的用户 Pydantic 模型。'''

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field


def _utc_now() -> datetime:
    '''返回带时区信息的当前 UTC 时间。'''
    return datetime.now(UTC)


class User(BaseModel):
    '''系统内部使用的用户表示。'''

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4, description="Primary key")
    email: EmailStr = Field(..., description="Unique email address")
    password_hash: str | None = Field(None, description="bcrypt hash; absent until a local password is assigned")
    system_role: Literal["admin", "user"] = Field(default="user")
    created_at: datetime = Field(default_factory=_utc_now)

    # 认证生命周期状态
    needs_setup: bool = Field(default=False, description="True when a reset account must complete setup")
    token_version: int = Field(default=0, description="Incremented on password change to invalidate old JWTs")


class UserResponse(BaseModel):
    '''用户信息接口的响应模型。'''

    id: str
    email: str
    system_role: Literal["admin", "user"]
    needs_setup: bool = False
