'''描述本地账号与 OIDC 登录提供者的认证配置。'''

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OIDCProviderConfig(BaseModel):
    '''保存单个 OIDC 提供者的端点、客户端凭据及用户准入策略。'''

    display_name: str = Field(description="Human-readable name shown on the login button")
    issuer: str = Field(description="OIDC issuer URL (e.g. https://keycloak.example.com/realms/deerflow)")
    client_id: str = Field(description="OAuth2 client ID assigned by the provider")
    client_secret: str | None = Field(default=None, description="OAuth2 client secret ($ENV_VAR references supported)")
    redirect_uri: str | None = Field(default=None, description="Callback URL the provider will redirect to after auth")
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"],
        description="OIDC scopes to request (must include openid)",
    )
    token_endpoint_auth_method: Literal["client_secret_post", "client_secret_basic", "none"] = Field(
        default="client_secret_post",
        description="How the client authenticates at the token endpoint",
    )
    auto_create_users: bool = Field(
        default=True,
        description="Automatically create a DeerFlow user on first SSO login",
    )
    require_verified_email: bool = Field(
        default=True,
        description="Reject authentication if the provider does not report the email as verified",
    )
    allowed_email_domains: list[str] = Field(
        default_factory=list,
        description="If non-empty, only allow users whose email domain is in this list (e.g. ['example.com'])",
    )
    admin_emails: list[str] = Field(
        default_factory=list,
        description="Users with these email addresses are automatically granted the admin role on first login",
    )
    pkce_enabled: bool = Field(default=True, description="Enable PKCE (S256) for the authorization code flow")
    nonce_enabled: bool = Field(default=True, description="Include and validate the nonce claim in ID tokens")
    authorization_endpoint: str | None = Field(default=None)
    token_endpoint: str | None = Field(default=None)
    userinfo_endpoint: str | None = Field(default=None)
    jwks_uri: str | None = Field(default=None)


class OIDCAuthConfig(BaseModel):
    '''控制 OIDC 登录入口以及可用身份提供者列表。'''

    enabled: bool = Field(default=False, description="Enable OIDC SSO authentication")
    frontend_base_url: str | None = Field(
        default=None,
        description="Base URL of the frontend (used for callback redirects when behind a reverse proxy)",
    )
    providers: dict[str, OIDCProviderConfig] = Field(
        default_factory=dict,
        description="Map of provider IDs to their configuration (e.g. keycloak, google, azure)",
    )


class AuthAppConfig(BaseModel):
    '''汇总登录方式、会话令牌、安全限制和初始管理员设置。'''

    oidc: OIDCAuthConfig = Field(default_factory=OIDCAuthConfig, description="OIDC SSO authentication settings")
