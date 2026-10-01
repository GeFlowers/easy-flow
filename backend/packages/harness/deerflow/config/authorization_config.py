'''定义细粒度授权提供者、默认角色及失败时的访问策略。'''

from pydantic import BaseModel, Field


class AuthorizationProviderConfig(BaseModel):
    '''指定授权实现类及传给该实现的初始化参数。'''

    use: str = Field(description="Class path (e.g. 'deerflow.authz.rbac:RbacAuthorizationProvider')")
    config: dict = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


class AuthorizationConfig(BaseModel):
    '''控制授权开关、失败关闭行为、默认角色和提供者实现。'''

    enabled: bool = Field(default=False, description="Enable fine-grained authorization")
    fail_closed: bool = Field(default=True, description="Block access if the provider errors or identity is unresolved")
    default_role: str = Field(default="user", description="Role applied when user_role is None (e.g. unbound IM channels)")
    provider: AuthorizationProviderConfig | None = Field(default=None, description="Authorization provider configuration")


_authorization_config: AuthorizationConfig | None = None


def get_authorization_config() -> AuthorizationConfig:
    '''返回授权配置；尚未加载时创建默认配置并缓存。'''
    global _authorization_config
    if _authorization_config is None:
        _authorization_config = AuthorizationConfig()
    return _authorization_config


def load_authorization_config_from_dict(data: dict) -> AuthorizationConfig:
    '''校验字典字段并用新值替换当前授权配置。'''
    global _authorization_config
    _authorization_config = AuthorizationConfig.model_validate(data)
    return _authorization_config


def reset_authorization_config() -> None:
    '''清除授权配置缓存，使后续读取重新使用默认值或重新加载。'''
    global _authorization_config
    _authorization_config = None
