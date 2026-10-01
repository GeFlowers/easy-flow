'''为 OIDC 登录配置用户。

本模块查找已有用户、按规则自动创建用户并限制邮箱域名。已有本地账户绝不自动
绑定 OIDC 身份；邮箱冲突会以 409 阻止 SSO 登录，避免 SSO 身份接管密码账户。
'''

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.oidc import OIDCIdentity
from deerflow.config.auth_config import OIDCProviderConfig

logger = logging.getLogger(__name__)


async def get_or_provision_oidc_user(
    provider_id: str,
    provider_config: OIDCProviderConfig,
    identity: OIDCIdentity,
    local_provider: LocalAuthProvider,
) -> dict:
    '''将 OIDC 身份解析为 DeerFlow 用户，并保持本地账户与 SSO 身份隔离。'''
    # 1. 已有关联的第三方登录身份
    existing = await local_provider.get_user_by_oauth(provider_id, identity.subject)
    if existing:
        return {"user": existing, "created": False}

    # 2. 必须满足已验证邮箱要求
    if provider_config.require_verified_email and not identity.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Your email could not be verified by the identity provider. Please contact your administrator."),
        )

    if not identity.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The identity provider did not provide an email address.",
        )

    email = identity.email.lower()

    # 3. 邮箱域名限制
    if provider_config.allowed_email_domains:
        domain = email.rsplit("@", 1)[-1]
        if domain not in {d.lower().lstrip("@") for d in provider_config.allowed_email_domains}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your email domain is not allowed. Please use an approved email address.",
            )

    # 4. 若本地账户已占用该邮箱则阻止登录。绝不把单点登录身份自动关联到已有本地
    # 账户，否则同邮箱的单点登录可能接管该密码账户。
    local_user = await local_provider.get_user_by_email(email)

    if local_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("An account with this email already exists. Contact your administrator to link it to your SSO account."),
        )

    # 5. 自动创建用户
    if not provider_config.auto_create_users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Automatic account creation is disabled. Contact your administrator.",
        )

    role = _resolve_role(email, provider_config.admin_emails)
    try:
        user = await local_provider.create_oauth_user(
            email=email,
            oauth_provider=provider_id,
            oauth_id=identity.subject,
            system_role=role,
        )
    except ValueError:
        # 并发回调（双击或重放授权码）可能已插入触发唯一索引冲突的行。重新解析而
        # 非抛出原始 500：若胜者创建了同一身份则返回它，否则邮箱现属另一账户并返回 409。
        existing = await local_provider.get_user_by_oauth(provider_id, identity.subject)
        if existing:
            return {"user": existing, "created": False}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("An account with this email already exists. Contact your administrator to link it to your SSO account."),
        ) from None
    logger.info("Auto-created OIDC user %s (provider=%s, role=%s)", email, provider_id, role)
    return {"user": user, "created": True}


def _resolve_role(email: str, admin_emails: list[str]) -> str:
    '''邮箱在管理员名单中时返回 ``admin``，否则返回 ``user``。'''
    email_lower = email.lower()
    return "admin" if any(e.lower() == email_lower for e in admin_emails) else "user"
