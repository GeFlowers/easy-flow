'''

运行上下文中的请求级密钥载体（问题 #3861）。

调用方通过 ``config.context.secrets`` 在常规输入之外传递请求级密钥，
其形式为名称到值的映射。密钥值不会进入提示词、工具参数或执行命令字符串；
仅当已激活技能在文档头部的 ``required-secrets`` 字段中声明密钥时，
才会以环境变量形式注入该技能的沙箱子进程。

本模块集中定义保留键名及安全提取逻辑，统一密钥载体约定。
技能激活中间件据此构建每轮注入集合，追踪脱敏器据此从追踪数据中移除密钥。
'''

from __future__ import annotations

from typing import Any

SECRETS_CONTEXT_KEY = "secrets"

ACTIVE_SECRETS_CONTEXT_KEY = "__active_skill_secrets"


def _string_pairs(raw: Any) -> dict[str, str]:
    '''筛出键和值均为字符串的密钥映射项，忽略不可信的其他类型。'''
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)}


def extract_request_secrets(context: Any) -> dict[str, str]:
    '''从运行上下文读取调用方提供的请求级密钥，并过滤非字符串项。'''
    if not isinstance(context, dict):
        return {}
    return _string_pairs(context.get(SECRETS_CONTEXT_KEY))


def read_active_secrets(context: Any) -> dict[str, str]:
    '''读取当前激活技能可注入子进程的密钥集合。'''
    if not isinstance(context, dict):
        return {}
    return _string_pairs(context.get(ACTIVE_SECRETS_CONTEXT_KEY))


_SLASH_SECRET_SOURCE_KEY = "__slash_skill_secret_source"
_SECRETS_BINDING_AUDIT_KEY = "__skill_secrets_binding_audit"

_SLASH_SKILL_ACTIVATION_RUN_KEY = "__slash_skill_activation_run"

REDACTED_CONTEXT_KEYS = frozenset(
    {
        SECRETS_CONTEXT_KEY,
        ACTIVE_SECRETS_CONTEXT_KEY,
        _SLASH_SECRET_SOURCE_KEY,
        _SECRETS_BINDING_AUDIT_KEY,
        _SLASH_SKILL_ACTIVATION_RUN_KEY,
    }
)


def redact_secret_context_keys(context: Any) -> Any:
    '''复制运行上下文并移除密钥及其绑定审计字段，避免序列化时泄漏。'''
    if not isinstance(context, dict):
        return context
    return {key: value for key, value in context.items() if key not in REDACTED_CONTEXT_KEYS}


def redact_config_secrets(config: Any) -> Any:
    '''生成可持久化或回传客户端的运行配置副本，并从 context 中剔除密钥。'''
    if not isinstance(config, dict):
        return config
    context = config.get("context")
    if not isinstance(context, dict):
        return config
    redacted = dict(config)
    redacted["context"] = redact_secret_context_keys(context)
    return redacted
