"""提供配置、authorization、配置相关功能。"""

from pydantic import BaseModel, Field


class AuthorizationProviderConfig(BaseModel):
    """\u6267\u884c AuthorizationProviderConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    use: str = Field(description="Class path (e.g. 'deerflow.authz.rbac:RbacAuthorizationProvider')")
    config: dict = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


class AuthorizationConfig(BaseModel):
    """\u6267\u884c AuthorizationConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(default=False, description="Enable fine-grained authorization")
    fail_closed: bool = Field(default=True, description="Block access if the provider errors or identity is unresolved")
    default_role: str = Field(default="user", description="Role applied when user_role is None (e.g. unbound IM channels)")
    provider: AuthorizationProviderConfig | None = Field(default=None, description="Authorization provider configuration")


_authorization_config: AuthorizationConfig | None = None


def get_authorization_config() -> AuthorizationConfig:
    """\u6267\u884c get_authorization_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _authorization_config
    if _authorization_config is None:
        _authorization_config = AuthorizationConfig()
    return _authorization_config


def load_authorization_config_from_dict(data: dict) -> AuthorizationConfig:
    """\u6267\u884c load_authorization_config_from_dict \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _authorization_config
    _authorization_config = AuthorizationConfig.model_validate(data)
    return _authorization_config


def reset_authorization_config() -> None:
    """\u6267\u884c reset_authorization_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _authorization_config
    _authorization_config = None
