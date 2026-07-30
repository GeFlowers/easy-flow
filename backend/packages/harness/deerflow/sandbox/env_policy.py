"""定义沙箱进程环境变量的筛选策略。"""

from __future__ import annotations

import fnmatch
import os

# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
_SECRET_NAME_PATTERNS: tuple[str, ...] = (
    "*KEY*",
    "*SECRET*",
    "*TOKEN*",
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
    #
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
    #
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
    "*PASS*",
    "*CREDENTIAL*",
    "*DSN*",                # 中文说明：此处用于执行相关处理。
)

# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
#
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
_BLOCKED_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "DATABASE_URI",
        "REDIS_URL",
        "MONGODB_URI",
        "MONGO_URL",
        "AMQP_URL",
        "RABBITMQ_URL",
        "POSTGRES_URL",
        "POSTGRESQL_URL",
        "MYSQL_URL",
        "CLICKHOUSE_URL",
        "CONNECTION_STRING",
        "CONN_STR",
        "GH_PAT",
        "GITHUB_PAT",
        "MYSQL_PWD",
        "REDISCLI_AUTH",
        "REDIS_AUTH",
        "PGSERVICEFILE",
    }
)


def is_blocked_env_name(name: str) -> bool:
    """判断环境变量名是否应从继承的沙箱环境中排除。"""
    upper = name.upper()
    if upper in _BLOCKED_EXACT_NAMES:
        return True
    return any(fnmatch.fnmatchcase(upper, pattern) for pattern in _SECRET_NAME_PATTERNS)


def build_sandbox_env(injected: dict[str, str] | None = None) -> dict[str, str]:
    """构建已排除敏感宿主变量并可叠加显式变量的沙箱环境。"""
    env = {key: value for key, value in os.environ.items() if not is_blocked_env_name(key)}
    if injected:
        env.update(injected)
    return env
